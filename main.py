import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
import threading
import time
import random
from decimal import Decimal, ROUND_DOWN, ROUND_UP, getcontext

# --- Configuration ---
BINANCE_CLIENT = None
LEVERAGE = 20
PNL_UPDATE_INTERVAL_SECONDS = 10 # For display updates
TARGET_MONITOR_INTERVAL_SECONDS = 3 # How often the auto-TP thread checks PNL
QUOTE_ASSET = "USDC"
getcontext().prec = 18

# --- Global Variables ---
pnl_update_thread = None
stop_pnl_thread = threading.Event()

# --- NEW: Target Profit Monitoring Globals ---
target_monitor_thread = None
stop_target_monitor_event = threading.Event()

# --- Binance Interaction Functions ---
# connect_binance, get_futures_symbol_filters, adjust_quantity_to_precision,
# adjust_price_to_precision, place_futures_order_with_tp, place_closing_order
# get_open_positions_pnl - These functions remain the same as in the previous version.
# ... (Keep the existing functions here - no changes needed in them) ...
def connect_binance(api_key, api_secret, testnet=False):
    global BINANCE_CLIENT
    try:
        BINANCE_CLIENT = Client(api_key, api_secret, testnet=testnet)
        BINANCE_CLIENT.ping(); print("Binance Connection Successful! Checking Settings...")
        account_info = BINANCE_CLIENT.futures_account_balance()
        try:
            position_mode = BINANCE_CLIENT.futures_get_position_mode()
            if not position_mode.get('dualSidePosition'):
                 print("CRITICAL Warning: Hedge Mode MUST be enabled in Binance Futures Settings."); messagebox.showwarning("Hedge Mode Required", "Hedge Mode MUST be enabled.")
        except BinanceAPIException as e: print(f"Could not check position mode: {e}")
        return True, "Connected successfully!"
    except BinanceAPIException as e: BINANCE_CLIENT = None; print(f"API Error: {e}"); return False, f"API Error: {e.message}"
    except Exception as e: BINANCE_CLIENT = None; print(f"Connection Error: {e}"); return False, f"Connection Error: {e}"

def get_futures_symbol_filters(symbol):
    if not BINANCE_CLIENT: return None, None
    try:
        info = BINANCE_CLIENT.futures_exchange_info(); qty_precision, price_precision = None, None
        for s in info['symbols']:
            if s['symbol'] == symbol:
                for f in s['filters']:
                    if f['filterType'] == 'LOT_SIZE': qty_precision = abs(Decimal(f['stepSize']).as_tuple().exponent) if Decimal(f['stepSize']).as_tuple().exponent < 0 else 0
                    elif f['filterType'] == 'PRICE_FILTER': price_precision = abs(Decimal(f['tickSize']).as_tuple().exponent) if Decimal(f['tickSize']).as_tuple().exponent < 0 else 0
                if qty_precision is not None and price_precision is not None: return qty_precision, price_precision
                else: print(f"Warning: Missing filters for {symbol}"); return qty_precision, price_precision
    except BinanceAPIException as e: print(f"Error fetching filters for {symbol}: {e}")
    return None, None

def adjust_quantity_to_precision(quantity, precision):
    if precision is None: print("Warning: No qty precision."); return round(quantity, 6)
    dq = Decimal(str(quantity)); step = Decimal('1')/(Decimal('10')**precision); return float(dq.quantize(step, rounding=ROUND_DOWN))

def adjust_price_to_precision(price, precision):
    if precision is None: print("Warning: No price precision."); return round(price, 4)
    dp = Decimal(str(price)); tick = Decimal('1')/(Decimal('10')**precision); return float(dp.quantize(tick, rounding=ROUND_HALF_UP))

def place_futures_order_with_tp(symbol, side, position_side, quantity, tp_price=None):
    global LEVERAGE; entry_order, tp_result = None, None
    if not BINANCE_CLIENT: return None, "ENTRY: Not connected.", None
    try:
        try: BINANCE_CLIENT.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)
        except BinanceAPIException as e:
            if "leverage not modified" not in str(e).lower(): raise BinanceAPIException(request=None, response=None, message=f"Leverage Error: {e}")
        qty_prec, price_prec = get_futures_symbol_filters(symbol)
        adj_qty = adjust_quantity_to_precision(quantity, qty_prec)
        if adj_qty <= 0: return None, f"ENTRY ({symbol}): Qty=0.", None
        entry_order = BINANCE_CLIENT.futures_create_order(symbol=symbol, side=side, positionSide=position_side, type=Client.ORDER_TYPE_MARKET, quantity=adj_qty)
        print(f"Entry: {symbol} ID {entry_order.get('orderId')}")
        if entry_order and tp_price and tp_price > 0:
            tp_side = Client.SIDE_SELL if side == Client.SIDE_BUY else Client.SIDE_BUY
            adj_tp_price = adjust_price_to_precision(tp_price, price_prec)
            if adj_tp_price <= 0: tp_result = f"TP ({symbol}): Failed - Invalid TP price."
            else:
                try:
                    tp_order = BINANCE_CLIENT.futures_create_order(symbol=symbol, side=tp_side, positionSide=position_side, type=Client.ORDER_TYPE_TAKE_PROFIT_MARKET, stopPrice=adj_tp_price, quantity=adj_qty, timeInForce=Client.TIME_IN_FORCE_GTC, reduceOnly=True)
                    tp_result = f"TP ({symbol}): Success - ID {tp_order.get('orderId', 'N/A')}"
                except (BinanceAPIException, BinanceOrderException) as e: tp_result = f"TP ({symbol}): Failed - {e.message}"
                except Exception as e: tp_result = f"TP ({symbol}): Failed - Generic: {e}"
            print(tp_result)
        entry_msg = f"Entry ({symbol}): Success - ID {entry_order.get('orderId', 'N/A')}"
        return entry_order, entry_msg, tp_result
    except (BinanceAPIException, BinanceOrderException) as e: return None, f"Entry ({symbol}): Failed - {e.message}", tp_result
    except Exception as e: return None, f"Entry ({symbol}): Failed - {e}", tp_result

def place_closing_order(symbol, position_side, quantity_to_close):
    if not BINANCE_CLIENT: return None, f"CLOSE ({symbol}): Not connected."
    side = Client.SIDE_SELL if position_side == 'LONG' else Client.SIDE_BUY
    try:
        qty_prec, _ = get_futures_symbol_filters(symbol)
        adj_qty = adjust_quantity_to_precision(quantity_to_close, qty_prec)
        if adj_qty <= 0: return None, f"CLOSE ({symbol}): Qty=0."
        order = BINANCE_CLIENT.futures_create_order(symbol=symbol, side=side, positionSide=position_side, type=Client.ORDER_TYPE_MARKET, quantity=adj_qty, reduceOnly=True)
        print(f"Close: {symbol} ID {order.get('orderId')}")
        return order, f"CLOSE ({symbol}): Success - ID {order.get('orderId', 'N/A')}"
    except (BinanceAPIException, BinanceOrderException) as e: return None, f"Close Error ({symbol}): {e.message}"
    except Exception as e: return None, f"Generic Close Error ({symbol}): {e}"

def get_open_positions_pnl():
    if not BINANCE_CLIENT: return "Not connected.", {}, Decimal(0)
    try:
        positions = BINANCE_CLIENT.futures_position_information(); open_positions = {}; total_pnl = Decimal(0)
        if not positions: return "No positions info.", {}, Decimal(0)
        for pos in positions:
            pos_amt = Decimal(pos.get('positionAmt', '0')); symbol = pos.get('symbol'); pos_side = pos.get('positionSide', 'N/A'); key = f"{symbol}_{pos_side}"
            if pos_amt != Decimal(0):
                try:
                    pnl = Decimal(pos.get('unRealizedProfit', '0')); total_pnl += pnl
                    entry = Decimal(pos.get('entryPrice', '0')); lev = pos.get('leverage', 'N/A'); margin_asset = pos.get('marginAsset', 'N/A')
                    mark_info = BINANCE_CLIENT.futures_mark_price(symbol=symbol); mark = Decimal(mark_info['markPrice'])
                    pnl_pct = Decimal(0)
                    if entry != Decimal(0) and lev != 'N/A' and mark != Decimal(0):
                        try:
                            lev_dec = Decimal(lev)
                            if lev_dec > 0: initial_margin = (abs(pos_amt)*mark)/lev_dec; pnl_pct = (pnl/initial_margin)*100 if initial_margin!=Decimal(0) else Decimal(0)
                        except Exception: pass
                    open_positions[key] = {'symbol': symbol, 'amount': float(pos_amt), 'entry_price': float(entry), 'mark_price': float(mark), 'pnl': pnl, 'pnl_percent': float(pnl_pct), 'leverage': lev, 'side': pos_side, 'margin_asset': margin_asset, 'raw_amount': pos_amt}
                except (BinanceAPIException, KeyError, ValueError, TypeError) as e: print(f"Error processing PNL {symbol}: {e}"); open_positions[key] = {'symbol': symbol, 'side': pos_side, 'error': f'PNL data error: {e}'}
        status = f"PNL ({len(open_positions)} Pos). Total: {total_pnl:.4f} {QUOTE_ASSET}"
        if not open_positions: status = "No active positions."
        return status, open_positions, total_pnl
    except BinanceAPIException as e: return f"API Error PNL: {e.message}", {}, Decimal(0)
    except Exception as e: return f"Error PNL: {e}", {}, Decimal(0)


# --- GUI Class ---

class BinanceTraderApp:
    def __init__(self, master):
        self.master = master
        master.title(f"Auto TP Futures Trader ({QUOTE_ASSET} - TESTNET FIRST!)") # Updated Title
        master.geometry("950x750")

        self.coin_vars = {}; self.side_vars = {}; self.tp_price_vars = {}
        self.add_long_buttons = {}; self.add_short_buttons = {}

        # --- NEW: State for Target Monitoring ---
        self.target_monitoring_active = False
        self.active_target_profit = Decimal(0)

        self.style = ttk.Style(); self.style.theme_use('clam')
        self.style.configure('Red.TButton', foreground='white', background='#d9534f') # Softer red
        self.style.configure('Green.TButton', foreground='white', background='#5cb85c') # Softer green
        self.style.configure('Orange.TButton', foreground='white', background='#f0ad4e') # Orange for active monitoring

        # --- Frames Setup --- (Same structure)
        self.top_frame = ttk.Frame(master); self.top_frame.pack(pady=5, padx=10, fill="x")
        self.connection_frame = ttk.LabelFrame(self.top_frame, text="1. Connect"); self.connection_frame.pack(side="left", padx=5, fill="y", anchor='n')
        self.settings_frame = ttk.LabelFrame(self.top_frame, text="2. Settings"); self.settings_frame.pack(side="left", padx=5, fill="y", anchor='n')
        self.trade_setup_frame = ttk.LabelFrame(master, text="3. Trade Setup (Symbols loaded after connect)"); self.trade_setup_frame.pack(pady=5, padx=10, fill="x")
        self.amount_management_frame = ttk.Frame(master); self.amount_management_frame.pack(pady=5, padx=10, fill="x")
        self.multi_amount_frame = ttk.LabelFrame(self.amount_management_frame, text=f"4a. Multi-Trade Total {QUOTE_ASSET}"); self.multi_amount_frame.pack(side="left", padx=5, fill="y")
        self.single_amount_frame = ttk.LabelFrame(self.amount_management_frame, text=f"4b. Single Add Amount ({QUOTE_ASSET})"); self.single_amount_frame.pack(side="left", padx=5, fill="y")
        self.action_frame = ttk.LabelFrame(master, text="5. Actions"); self.action_frame.pack(pady=5, padx=10, fill="x")
        self.pnl_frame = ttk.LabelFrame(master, text=f"6. Live Profit/Loss ({QUOTE_ASSET} - Updates ~{PNL_UPDATE_INTERVAL_SECONDS}s)"); self.pnl_frame.pack(pady=5, padx=10, fill="both", expand=True)
        self.status_frame = ttk.Frame(master); self.status_frame.pack(pady=5, padx=10, fill="x")

        # --- Connection & Settings Widgets --- (Same)
        ttk.Label(self.connection_frame, text="API Key:").grid(row=0, column=0, padx=5, pady=2, sticky="w"); self.api_key_entry = ttk.Entry(self.connection_frame, width=30, show="*"); self.api_key_entry.grid(row=0, column=1, padx=5, pady=2)
        ttk.Label(self.connection_frame, text="Secret Key:").grid(row=1, column=0, padx=5, pady=2, sticky="w"); self.api_secret_entry = ttk.Entry(self.connection_frame, width=30, show="*"); self.api_secret_entry.grid(row=1, column=1, padx=5, pady=2)
        self.testnet_var = tk.BooleanVar(value=True); self.testnet_check = ttk.Checkbutton(self.connection_frame, text="Use Testnet", variable=self.testnet_var); self.testnet_check.grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.connect_button = ttk.Button(self.connection_frame, text="Connect", command=self.connect); self.connect_button.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        ttk.Label(self.settings_frame, text="Leverage:").grid(row=0, column=0, padx=5, pady=2, sticky="w"); self.leverage_var = tk.StringVar(value=str(LEVERAGE)); self.leverage_entry = ttk.Entry(self.settings_frame, width=5, textvariable=self.leverage_var); self.leverage_entry.grid(row=0, column=1, padx=5, pady=2)
        self.set_leverage_button = ttk.Button(self.settings_frame, text="Set", command=self.set_leverage, width=4); self.set_leverage_button.grid(row=0, column=2, padx=5, pady=2); self.set_leverage_button.config(state=tk.DISABLED)

        # --- Trade Setup Frame Structure --- (Same)
        self.coin_selection_canvas = tk.Canvas(self.trade_setup_frame); self.coin_scrollbar = ttk.Scrollbar(self.trade_setup_frame, orient="vertical", command=self.coin_selection_canvas.yview); self.scrollable_frame = ttk.Frame(self.coin_selection_canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.coin_selection_canvas.configure(scrollregion=self.coin_selection_canvas.bbox("all"))); self.coin_selection_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw"); self.coin_selection_canvas.configure(yscrollcommand=self.coin_scrollbar.set)
        self.coin_selection_canvas.pack(side="left", fill="both", expand=True); self.coin_scrollbar.pack(side="right", fill="y"); self.trade_setup_frame.config(height=200)
        self._clear_coin_list_gui()

        # --- Amount Widgets --- (Same)
        ttk.Label(self.multi_amount_frame, text="Total:").pack(side="left", padx=2, pady=5); self.multi_amount_entry = ttk.Entry(self.multi_amount_frame, width=12); self.multi_amount_entry.pack(side="left", padx=2, pady=5); self.multi_amount_entry.insert(0, "100")
        ttk.Label(self.single_amount_frame, text="Amount:").pack(side="left", padx=2, pady=5); self.single_amount_entry = ttk.Entry(self.single_amount_frame, width=12); self.single_amount_entry.pack(side="left", padx=2, pady=5); self.single_amount_entry.insert(0, "10")

        # --- Action Widgets ---
        self.main_action_frame = ttk.Frame(self.action_frame); self.main_action_frame.pack(side="left", fill="x", expand=True)
        self.trade_button = ttk.Button(self.main_action_frame, text=f"Place Selected ({LEVERAGE}x)", command=self.place_multi_trades); self.trade_button.pack(side="left", padx=5, pady=5); self.trade_button.config(state=tk.DISABLED)
        self.random_select_button = ttk.Button(self.main_action_frame, text="Select Rand 10", command=self.select_random_coins); self.random_select_button.pack(side="left", padx=5, pady=5); self.random_select_button.config(state=tk.DISABLED)

        self.closing_action_frame = ttk.Frame(self.action_frame); self.closing_action_frame.pack(side="right")
        ttk.Label(self.closing_action_frame, text=f"Target Profit ({QUOTE_ASSET}):").pack(side="left", padx=5, pady=5)
        self.target_profit_var = tk.StringVar(value="1"); self.target_profit_entry = ttk.Entry(self.closing_action_frame, width=8, textvariable=self.target_profit_var); self.target_profit_entry.pack(side="left", padx=5, pady=5)

        # --- MODIFIED: Target Profit Button (Now Toggle) ---
        self.toggle_target_tp_button = ttk.Button(self.closing_action_frame, text="ACTIVATE Target TP", command=self.toggle_target_profit_monitor, style='Green.TButton');
        self.toggle_target_tp_button.pack(side="left", padx=10, pady=5); self.toggle_target_tp_button.config(state=tk.DISABLED)

        self.close_all_button = ttk.Button(self.closing_action_frame, text="CLOSE ALL NOW", command=self.close_all_positions, style='Red.TButton'); self.close_all_button.pack(side="left", padx=5, pady=5); self.close_all_button.config(state=tk.DISABLED)

        # --- PNL & Status Widgets --- (Same)
        self.pnl_text = scrolledtext.ScrolledText(self.pnl_frame, wrap=tk.WORD, height=10, state=tk.DISABLED); self.pnl_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.pnl_text.tag_config('profit', foreground='#5cb85c'); self.pnl_text.tag_config('loss', foreground='#d9534f'); self.pnl_text.tag_config('neutral', foreground='black')
        self.pnl_text.tag_config('header', font=('TkDefaultFont', 10, 'bold')); self.pnl_text.tag_config('error', foreground='orange red')
        self.pnl_text.tag_config('pnl_pos', foreground='#5cb85c', font=('TkDefaultFont', 9, 'bold')); self.pnl_text.tag_config('pnl_neg', foreground='#d9534f', font=('TkDefaultFont', 9, 'bold')); self.pnl_text.tag_config('pnl_zero', foreground='black', font=('TkDefaultFont', 9, 'bold'))
        self.status_var = tk.StringVar(); self.status_label = ttk.Label(self.status_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w"); self.status_label.pack(fill="x")
        self.set_status("Not connected. Ensure Hedge Mode is ON.")

        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --- GUI Build/Clear Methods --- (Same as before)
    def _build_coin_list_gui(self, symbols):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        self.coin_vars.clear(); self.side_vars.clear(); self.tp_price_vars.clear(); self.add_long_buttons.clear(); self.add_short_buttons.clear()
        ttk.Label(self.scrollable_frame, text="Coin", font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=0, padx=5, pady=2, sticky="w"); ttk.Label(self.scrollable_frame, text="Sel", font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=1, padx=1, pady=2); ttk.Label(self.scrollable_frame, text="Dir.", font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=2, columnspan=2, padx=2, pady=2); ttk.Label(self.scrollable_frame, text="TP Price", font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=4, padx=5, pady=2); ttk.Label(self.scrollable_frame, text="Single Add", font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=5, columnspan=2, padx=5, pady=2)
        for i, coin in enumerate(symbols):
            ttk.Label(self.scrollable_frame, text=coin).grid(row=i + 1, column=0, padx=5, pady=1, sticky="w"); var = tk.BooleanVar(); cb = ttk.Checkbutton(self.scrollable_frame, variable=var); cb.grid(row=i + 1, column=1, padx=1, pady=1); self.coin_vars[coin] = var
            side_var = tk.StringVar(value="LONG"); long_rb = ttk.Radiobutton(self.scrollable_frame, text="L", variable=side_var, value="LONG", width=2); short_rb = ttk.Radiobutton(self.scrollable_frame, text="S", variable=side_var, value="SHORT", width=2); long_rb.grid(row=i + 1, column=2, padx=0, pady=1, sticky="w"); short_rb.grid(row=i + 1, column=3, padx=0, pady=1, sticky="w"); self.side_vars[coin] = side_var
            tp_var = tk.StringVar(); tp_entry = ttk.Entry(self.scrollable_frame, width=8, textvariable=tp_var); tp_entry.grid(row=i + 1, column=4, padx=2, pady=1); self.tp_price_vars[coin] = tp_var
            add_long_btn = ttk.Button(self.scrollable_frame, text="L+", width=3, state=tk.NORMAL, command=lambda c=coin: self.add_single_position(c, "LONG")); add_short_btn = ttk.Button(self.scrollable_frame, text="S+", width=3, state=tk.NORMAL, command=lambda c=coin: self.add_single_position(c, "SHORT")); add_long_btn.grid(row=i + 1, column=5, padx=1, pady=1); add_short_btn.grid(row=i + 1, column=6, padx=1, pady=1); self.add_long_buttons[coin] = add_long_btn; self.add_short_buttons[coin] = add_short_btn
        self.scrollable_frame.update_idletasks(); self.coin_selection_canvas.configure(scrollregion=self.coin_selection_canvas.bbox("all"))

    def _clear_coin_list_gui(self):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        self.coin_vars.clear(); self.side_vars.clear(); self.tp_price_vars.clear(); self.add_long_buttons.clear(); self.add_short_buttons.clear()
        ttk.Label(self.scrollable_frame, text="Connect to load symbols...").grid(row=0, column=0, padx=10, pady=10)
        self.scrollable_frame.update_idletasks(); self.coin_selection_canvas.configure(scrollregion=self.coin_selection_canvas.bbox("all"))

    # --- Action Button State Control ---
    def _set_action_buttons_state(self, state, monitor_active=False):
        """Sets state, considering if target monitoring is active."""
        trade_state = tk.DISABLED if monitor_active else state
        close_now_state = tk.DISABLED if monitor_active else state
        # Target TP button state is handled separately by toggle function

        buttons_config = {
            self.trade_button: trade_state,
            self.set_leverage_button: state, # Allow leverage change? Maybe disable if monitor active? Let's allow for now.
            self.close_all_button: close_now_state,
            self.random_select_button: trade_state, # Disable random select if monitoring
            self.toggle_target_tp_button: state # Master enable/disable, style/text handled by toggle
        }
        # Add individual buttons
        for btn in self.add_long_buttons.values(): buttons_config[btn] = trade_state
        for btn in self.add_short_buttons.values(): buttons_config[btn] = trade_state

        for btn, btn_state in buttons_config.items():
             if isinstance(btn, (ttk.Button, tk.Button)) and btn.winfo_exists():
                 try: btn.config(state=btn_state)
                 except tk.TclError as e: print(f"Warning: Btn state error: {e}")

    def set_status(self, message, error=False):
        self.status_var.set(message)
        self.status_label.config(foreground="red" if error else "black")
        print(f"Status: {message}")

    # --- Connection Logic --- (Handles enabling/disabling buttons)
    def connect(self):
        api_key = self.api_key_entry.get(); api_secret = self.api_secret_entry.get(); use_testnet = self.testnet_var.get()
        if not api_key or not api_secret: messagebox.showerror("Error", "API Key/Secret missing."); return
        self.set_status(f"Connecting..."); self.connect_button.config(state=tk.DISABLED); self.master.update_idletasks()
        threading.Thread(target=self._execute_connection, args=(api_key, api_secret, use_testnet), daemon=True).start()

    def _execute_connection(self, api_key, api_secret, use_testnet):
        global BINANCE_CLIENT, LEVERAGE
        if BINANCE_CLIENT: # Disconnect
             self.deactivate_target_profit_monitor() # Ensure monitor is stopped if active
             self.stop_pnl_updater(); BINANCE_CLIENT = None
             self._set_action_buttons_state(tk.DISABLED)
             self._clear_coin_list_gui(); self.set_status("Disconnected.")
             self.connect_button.config(text="Connect", state=tk.NORMAL)
             try:
                 if self.pnl_text.winfo_exists(): self.pnl_text.config(state=tk.NORMAL); self.pnl_text.delete('1.0', tk.END); self.pnl_text.insert(tk.END, "Disconnected.\n"); self.pnl_text.config(state=tk.DISABLED)
             except tk.TclError: pass
             return
        connect_success, connect_message = connect_binance(api_key, api_secret, testnet=use_testnet)
        if connect_success:
            try:
                print("Fetching symbols..."); exchange_info = BINANCE_CLIENT.futures_exchange_info()
                fetched_symbols = sorted([s['symbol'] for s in exchange_info['symbols'] if s.get('quoteAsset') == QUOTE_ASSET and s.get('contractType') == 'PERPETUAL' and s.get('status') == 'TRADING'])
                if not fetched_symbols:
                     fetch_message = f"Connected, but NO trading {QUOTE_ASSET} symbols found."
                     print(fetch_message); self.set_status(fetch_message, error=True); self._clear_coin_list_gui()
                     self._set_action_buttons_state(tk.DISABLED) # Disable most actions
                     self.set_leverage_button.config(state=tk.NORMAL); self.close_all_button.config(state=tk.NORMAL); self.toggle_target_tp_button.config(state=tk.NORMAL) # Allow closing/TP activation
                     self.start_pnl_updater()
                else:
                    print(f"Found {len(fetched_symbols)} symbols."); self._build_coin_list_gui(fetched_symbols)
                    self.set_status(connect_message + f" Found {len(fetched_symbols)} pairs.")
                    self._set_action_buttons_state(tk.NORMAL) # Enable all actions
                    self.connect_button.config(text="Disconnect", state=tk.NORMAL)
                    self.leverage_var.set(str(LEVERAGE)); self.trade_button.config(text=f"Place Selected ({LEVERAGE}x)")
                    self.start_pnl_updater()
            except BinanceAPIException as e:
                 print(f"Symbol fetch error: {e}"); self.set_status(f"Connected, symbol fetch error: {e}", error=True)
                 BINANCE_CLIENT = None; self._set_action_buttons_state(tk.DISABLED); self._clear_coin_list_gui(); self.connect_button.config(text="Connect", state=tk.NORMAL)
        else: # Connection failed
            self.set_status(f"Connection Failed: {connect_message}", error=True); messagebox.showerror("Connection Error", connect_message)
            self._set_action_buttons_state(tk.DISABLED); self._clear_coin_list_gui(); self.connect_button.config(text="Connect", state=tk.NORMAL)

    def set_leverage(self):
        global LEVERAGE
        if not BINANCE_CLIENT: messagebox.showerror("Error", "Not connected."); return
        try:
            new_leverage = int(self.leverage_var.get())
            if 1 <= new_leverage <= 125: LEVERAGE = new_leverage; self.trade_button.config(text=f"Place Selected ({LEVERAGE}x)"); self.set_status(f"Default leverage set to {LEVERAGE}x.")
            else: messagebox.showerror("Error", "Leverage must be 1-125.")
        except ValueError: messagebox.showerror("Error", "Invalid leverage number.")

    # --- Multi/Single Trade Logic --- (Same as before)
    def place_multi_trades(self):
        global BINANCE_CLIENT, LEVERAGE
        if not BINANCE_CLIENT: messagebox.showerror("Error", "Not connected."); return
        current_symbols = list(self.coin_vars.keys())
        if not current_symbols: messagebox.showerror("Error", "No symbols loaded."); return
        selected = []
        for coin, var in self.coin_vars.items():
            if var.get():
                tp = None; tp_str = self.tp_price_vars[coin].get().strip()
                if tp_str:
                    try: tp = float(tp_str); assert tp > 0
                    except (ValueError, AssertionError): tp = None
                selected.append({"symbol": coin, "position_side": self.side_vars[coin].get(), "tp_price": tp})
        if not selected: messagebox.showwarning("Warning", "No coins selected."); return
        try: total_amt = Decimal(self.multi_amount_entry.get()); assert total_amt > 0
        except (ValueError, TypeError, AssertionError): messagebox.showerror("Error", f"Invalid Multi-Trade amount."); return
        amt_per = total_amt / Decimal(len(selected))
        self.set_status(f"Preparing {len(selected)} trades ({LEVERAGE}x), ~{amt_per:.4f} {QUOTE_ASSET}..."); self.master.update_idletasks(); self._set_action_buttons_state(tk.DISABLED, monitor_active=self.target_monitoring_active)
        threading.Thread(target=self._execute_multi_trades, args=(selected, amt_per), daemon=True).start()

    def _execute_multi_trades(self, coins_to_trade, amount_per_coin):
        results = []; has_errors = False
        for info in coins_to_trade:
            symbol=info["symbol"]; pos_side=info["position_side"]; tp=info["tp_price"]; side=Client.SIDE_BUY if pos_side=="LONG" else Client.SIDE_SELL
            try:
                ticker=BINANCE_CLIENT.futures_mark_price(symbol=symbol); mark=Decimal(ticker['markPrice'])
                if mark <= 0: results.append(f"{symbol}: Error - Invalid mark"); has_errors=True; continue
                if tp:
                    tp_d = Decimal(str(tp))
                    if pos_side=="LONG" and tp_d <= mark: results.append(f"TP ({symbol}): Warn - TP ≤ Mark")
                    elif pos_side=="SHORT" and tp_d >= mark: results.append(f"TP ({symbol}): Warn - TP ≥ Mark")
                qty = float((amount_per_coin * Decimal(LEVERAGE)) / mark)
                order, entry_msg, tp_msg = place_futures_order_with_tp(symbol, side, pos_side, qty, tp)
                results.append(entry_msg);
                if tp_msg: results.append(tp_msg)
                if not order or "Failed" in entry_msg or (tp_msg and "Failed" in tp_msg): has_errors=True
            except (BinanceAPIException, KeyError, Exception) as e: results.append(f"{symbol}: Error - {e}"); has_errors=True
            time.sleep(0.2)
        summary = "Multi-trade finished."; err_msg = " (Check logs!)" if has_errors else ""
        self.set_status(summary + err_msg, error=has_errors); messagebox.showinfo("Multi-Trade Results", summary + err_msg + "\n\n" + "\n".join(results))
        if BINANCE_CLIENT: self._set_action_buttons_state(tk.NORMAL, monitor_active=self.target_monitoring_active) # Re-enable respecting monitor state

    def add_single_position(self, symbol, position_side):
        if not BINANCE_CLIENT: messagebox.showerror("Error", "Not connected."); return
        try: amount = Decimal(self.single_amount_entry.get()); assert amount > 0
        except (ValueError, TypeError, AssertionError): messagebox.showerror("Error", f"Invalid Single Add amount."); return
        self.set_status(f"Adding {position_side} {symbol} ({LEVERAGE}x)..."); self.master.update_idletasks(); self._set_action_buttons_state(tk.DISABLED, monitor_active=self.target_monitoring_active)
        threading.Thread(target=self._execute_single_add, args=(symbol, position_side, amount), daemon=True).start()

    def _execute_single_add(self, symbol, position_side, single_amount):
        side = Client.SIDE_BUY if position_side == "LONG" else Client.SIDE_SELL; msg = ""
        try:
            ticker = BINANCE_CLIENT.futures_mark_price(symbol=symbol); mark = Decimal(ticker['markPrice'])
            if mark <= 0: msg = f"ADD ({symbol}): Error - Invalid mark"
            else:
                qty = float((single_amount * Decimal(LEVERAGE)) / mark)
                order, entry_msg, _ = place_futures_order_with_tp(symbol, side, position_side, qty, None)
                msg = entry_msg
        except (BinanceAPIException, KeyError, Exception) as e: msg = f"ADD ({symbol}): Error - {e}"
        print(msg); is_err = ("Failed" in msg or "Error" in msg); self.set_status(msg, error=is_err)
        if not is_err: messagebox.showinfo("Single Add Result", msg)
        else: messagebox.showerror("Single Add Result", msg)
        if BINANCE_CLIENT: self._set_action_buttons_state(tk.NORMAL, monitor_active=self.target_monitoring_active)

    # --- Random Select --- (Same as before)
    def select_random_coins(self):
        num_long = 10; num_short = 0; total_needed = num_long + num_short
        current_symbols = list(self.coin_vars.keys())
        if len(current_symbols) < total_needed: messagebox.showwarning("Not Enough Coins", f"Need {total_needed} loaded symbols."); return
        for coin in current_symbols: self.coin_vars[coin].set(False); self.tp_price_vars[coin].set("")
        sample = random.sample(current_symbols, total_needed)
        for coin in sample[:num_long]: self.coin_vars[coin].set(True); self.side_vars[coin].set("LONG")
        for coin in sample[num_long:]: self.coin_vars[coin].set(True); self.side_vars[coin].set("SHORT")
        self.set_status(f"Selected {num_long} LONG / {num_short} SHORT.")

    # --- Close All Now --- (Same as before)
    def close_all_positions(self):
        if not BINANCE_CLIENT: messagebox.showerror("Error", "Not connected."); return
        if not messagebox.askyesno("Confirm Close All NOW", "CLOSE ALL positions NOW with MARKET orders?"): return
        self.set_status("Attempting to close all positions NOW..."); self.master.update_idletasks()
        self._set_action_buttons_state(tk.DISABLED) # Disable all during close
        # Pass monitor_triggered=False (default)
        threading.Thread(target=self._execute_close_all, daemon=True).start()


    # --- NEW: Target Profit Toggle and Monitor ---
    def toggle_target_profit_monitor(self):
        """Activates or deactivates the target profit monitoring thread."""
        if self.target_monitoring_active:
            self.deactivate_target_profit_monitor()
        else:
            self.activate_target_profit_monitor()

    def activate_target_profit_monitor(self):
        """Starts the background thread to monitor PNL against the target."""
        global target_monitor_thread
        if not BINANCE_CLIENT: messagebox.showerror("Error", "Not connected."); return

        try:
            target_profit_val = Decimal(self.target_profit_var.get())
            if target_profit_val <= 0: messagebox.showerror("Error", "Target Profit must be positive."); return
        except (ValueError, TypeError): messagebox.showerror("Error", "Invalid Target Profit value."); return

        # Check if already running (shouldn't happen with toggle logic, but safe check)
        if self.target_monitoring_active and target_monitor_thread and target_monitor_thread.is_alive():
             print("Monitor already active.")
             return

        self.target_monitoring_active = True
        self.active_target_profit = target_profit_val
        stop_target_monitor_event.clear() # Ensure stop event is clear

        # Update GUI
        self.toggle_target_tp_button.config(text="DEACTIVATE Target TP", style='Orange.TButton') # Change button
        self._set_action_buttons_state(tk.DISABLED, monitor_active=True) # Disable other actions, keep this one enabled
        self.toggle_target_tp_button.config(state=tk.NORMAL) # Ensure this button itself stays enabled
        self.target_profit_entry.config(state=tk.DISABLED) # Lock target profit entry while active


        self.set_status(f"Target TP Monitor ACTIVE for >= {self.active_target_profit:.4f} {QUOTE_ASSET}")

        # Start the monitor thread
        target_monitor_thread = threading.Thread(target=self._run_target_profit_monitor,
                                                 args=(self.active_target_profit,), daemon=True)
        target_monitor_thread.start()

    def deactivate_target_profit_monitor(self, closed_by_monitor=False):
        """Stops the monitoring thread and resets the GUI state."""
        global target_monitor_thread
        if not self.target_monitoring_active:
            # print("Monitor not active, nothing to deactivate.")
            return # Already inactive

        print("Deactivating Target TP Monitor...")
        self.target_monitoring_active = False
        stop_target_monitor_event.set() # Signal thread to stop

        # Wait briefly for thread to potentially finish (optional)
        if target_monitor_thread and target_monitor_thread.is_alive():
             target_monitor_thread.join(timeout=0.5) # Don't block GUI for long

        target_monitor_thread = None # Clear thread variable

        # --- Safely Update GUI using master.after ---
        def update_gui_on_deactivate():
            if not self.master.winfo_exists(): return # Check if window still exists
            try:
                 self.toggle_target_tp_button.config(text="ACTIVATE Target TP", style='Green.TButton')
                 self.target_profit_entry.config(state=tk.NORMAL) # Re-enable entry
                 # Re-enable other buttons only if connected
                 if BINANCE_CLIENT:
                     self._set_action_buttons_state(tk.NORMAL, monitor_active=False)
                 else:
                     self._set_action_buttons_state(tk.DISABLED) # Keep disabled if disconnected
                 # Update status only if not closed by monitor (close function sets its own status)
                 if not closed_by_monitor:
                     self.set_status("Target TP Monitor DEACTIVATED.")
            except tk.TclError as e:
                 print(f"GUI Error during deactivation: {e}") # Handle cases where widget might be destroyed

        self.master.after(0, update_gui_on_deactivate)


    def _run_target_profit_monitor(self, target_profit_level):
        """Background thread function that checks PNL."""
        print(f"Target TP Monitor thread started. Target: {target_profit_level:.4f} {QUOTE_ASSET}")
        closed_successfully = False

        while not stop_target_monitor_event.is_set():
            if not BINANCE_CLIENT:
                 print("Monitor Thread: Disconnected. Stopping monitor.")
                 break # Exit loop if disconnected

            try:
                # Fetch current PNL data
                status_msg, current_positions, current_total_pnl = get_open_positions_pnl()

                # Log current status for debugging
                # print(f"Monitor Check: Current PNL = {current_total_pnl:.4f}")

                if not current_positions:
                     print("Monitor Thread: No open positions found. Stopping monitor.")
                     messagebox.showinfo("Monitor Stopped", "No open positions remain. Target TP monitor stopped.")
                     break # Stop if positions disappear

                if current_total_pnl >= target_profit_level:
                    print(f"Monitor Thread: TARGET PROFIT >= {target_profit_level:.4f} REACHED! (Current: {current_total_pnl:.4f})")
                    self.set_status(f"Target >= {target_profit_level:.4f} HIT! Attempting MARKET close...")
                    # Trigger the close all mechanism directly from this thread
                    # Pass flag indicating it was triggered by monitor
                    # Note: _execute_close_all will run in *this* thread now
                    self._execute_close_all(triggered_by_monitor=True)
                    closed_successfully = True # Assume close was triggered
                    break # Exit loop after triggering close

                # Wait for the defined interval before the next check
                stop_target_monitor_event.wait(TARGET_MONITOR_INTERVAL_SECONDS)

            except Exception as e:
                 print(f"Error in Target Monitor Thread: {e}")
                 # Decide whether to continue or stop on error
                 # For now, let's log and continue, maybe add a counter later
                 time.sleep(TARGET_MONITOR_INTERVAL_SECONDS * 2) # Longer sleep on error

        # --- Loop finished (stopped manually, target hit, disconnected, or error) ---
        print("Target TP Monitor thread finished.")
        # Ensure state is reset via the main thread using 'after'
        # Pass whether it was stopped due to successful close
        self.master.after(0, lambda: self.deactivate_target_profit_monitor(closed_by_monitor=closed_successfully))


    # --- MODIFIED: Close All Execution ---
    def _execute_close_all(self, triggered_by_monitor=False):
        """Background thread to close all positions. Now accepts trigger source."""
        global BINANCE_CLIENT
        results = []; has_errors = False; positions_to_close = []
        final_status = "Close All Positions finished."

        try:
            positions = BINANCE_CLIENT.futures_position_information()
            for pos in positions:
                if Decimal(pos.get('positionAmt', '0')) != Decimal(0):
                    positions_to_close.append({'symbol': pos['symbol'], 'positionSide': pos['positionSide'], 'amount': abs(Decimal(pos['positionAmt']))})
            if not positions_to_close: results.append("No open positions found to close.")
            else:
                results.append(f"Found {len(positions_to_close)} positions. Sending MARKET close orders...")
                for pos_info in positions_to_close:
                    close_order, close_msg = place_closing_order(pos_info['symbol'], pos_info['positionSide'], float(pos_info['amount']))
                    results.append(close_msg)
                    if not close_order or "Failed" in close_msg or "Error" in close_msg: has_errors = True
                    time.sleep(0.15) # Delay between close orders
        except BinanceAPIException as e: results.append(f"CLOSE ALL: API Error - {e.message}"); has_errors = True
        except Exception as e: results.append(f"CLOSE ALL: Generic Error - {e}"); has_errors = True

        if triggered_by_monitor: final_status = "Target Profit triggered CLOSE ALL finished."
        if has_errors: final_status += " (Check logs!)"

        # --- Safely Update GUI after closing ---
        def update_gui_after_close():
             if not self.master.winfo_exists(): return
             try:
                 self.set_status(final_status, error=has_errors)
                 messagebox.showinfo("Close All Results", final_status + "\n\n" + "\n".join(results))
                 # If triggered by monitor, the monitor thread's exit will call deactivate.
                 # If triggered manually (red button), re-enable buttons here.
                 if not triggered_by_monitor:
                     if BINANCE_CLIENT:
                          self._set_action_buttons_state(tk.NORMAL, monitor_active=self.target_monitoring_active) # Respect monitor state
                     else:
                          self._set_action_buttons_state(tk.DISABLED)
             except tk.TclError as e:
                 print(f"GUI Error during close results: {e}")

        self.master.after(0, update_gui_after_close)


    # --- PNL Display and Threading (No changes needed here) ---
    def update_pnl_display(self):
        global stop_pnl_thread
        while not stop_pnl_thread.is_set():
            if BINANCE_CLIENT:
                status_msg, positions_data, total_pnl = get_open_positions_pnl()
                content = f"Status: {status_msg}\n" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
                if positions_data:
                    content += f"{'Symbol':<12} {'Side':<6} {'Amount':<15} {'Entry':<12} {'Mark':<12} {'Lev':<4} {'PNL ('+QUOTE_ASSET+')':<15} {'PNL (%)':<10}\n" + "-"*105 + "\n"
                    for pos_key, data in positions_data.items():
                         if 'error' in data: symbol = data.get('symbol', pos_key.split('_')[0]); side = data.get('side', 'N/A'); content += f"{symbol:<12} {side:<6} {'N/A':<15} {'N/A':<12} {'N/A':<12} {'N/A':<4} {data['error']:<15}\n"; continue
                         amount = data.get('amount', 0.0); entry = data.get('entry_price', 0.0); mark = data.get('mark_price', 0.0); pnl_val = data.get('pnl', Decimal(0)); pnl_percent = data.get('pnl_percent', 0.0); leverage = data.get('leverage', 'N/A'); side = data.get('side', 'N/A'); symbol = data.get('symbol')
                         content += f"{symbol:<12} {side:<6} {amount:<15.8f} {entry:<12.4f} {mark:<12.4f} {str(leverage)+'x':<4} {float(pnl_val):<15.4f} {pnl_percent:<10.2f}%\n"
                    content += "\n" + "="*105 + f"\nTotal Unrealized PNL: {float(total_pnl):.4f} {QUOTE_ASSET}\n"
                else:
                    content += "No open positions found or error fetching data.\n"
                    if "API Error" in status_msg or "Error fetching" in status_msg: content += f"\nError Detail: {status_msg}\n"
                try:
                    if self.pnl_text.winfo_exists():
                        self.pnl_text.config(state=tk.NORMAL); self.pnl_text.delete('1.0', tk.END); lines = content.splitlines(); is_header = True
                        for i, line in enumerate(lines):
                            line_content = line + "\n"; tags = ()
                            if i==0 and ("API Error" in line or "Error fetching" in line): tags = ('error',)
                            elif f"PNL ({QUOTE_ASSET})" in line or line.startswith("-----") or line.startswith("====="): tags = ('header',); is_header = False
                            elif not is_header and len(line.split()) > 5 and "PNL" not in line:
                                try: pnl_value = float(line.split()[-2]); tags = ('profit',) if pnl_value > 0 else ('loss',) if pnl_value < 0 else ('neutral',)
                                except: pass
                            elif f"Total Unrealized PNL:" in line: tags = ('pnl_pos',) if total_pnl > 0 else ('pnl_neg',) if total_pnl < 0 else ('pnl_zero',)
                            self.pnl_text.insert(tk.END, line_content, tags)
                        self.pnl_text.config(state=tk.DISABLED)
                except tk.TclError as e: print(f"PNL Update TclError: {e}"); break
                except Exception as e: print(f"Error updating PNL text: {e}")
            stop_pnl_thread.wait(PNL_UPDATE_INTERVAL_SECONDS)

    def start_pnl_updater(self):
        global pnl_update_thread, stop_pnl_thread
        if pnl_update_thread is None or not pnl_update_thread.is_alive():
            stop_pnl_thread.clear(); pnl_update_thread = threading.Thread(target=self.update_pnl_display, daemon=True)
            pnl_update_thread.start(); print("PNL Update thread started.")
            threading.Thread(target=self._trigger_immediate_pnl_update, daemon=True).start()

    def _trigger_immediate_pnl_update(self):
        if BINANCE_CLIENT:
             status_msg, _, _ = get_open_positions_pnl()
             content = f"Status: {status_msg}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n\nFetching initial PNL..."
             try:
                 if self.pnl_text.winfo_exists(): self.pnl_text.config(state=tk.NORMAL); self.pnl_text.delete('1.0', tk.END); self.pnl_text.insert(tk.END, content); self.pnl_text.config(state=tk.DISABLED)
             except tk.TclError: pass

    def stop_pnl_updater(self):
        global stop_pnl_thread, pnl_update_thread
        if pnl_update_thread and pnl_update_thread.is_alive():
            stop_pnl_thread.set(); print("PNL Update thread stopped.")
        pnl_update_thread = None

    def on_closing(self):
        print("Close button pressed...")
        self.deactivate_target_profit_monitor() # Stop monitor first
        self.stop_pnl_updater(); # Stop PNL display
        time.sleep(0.3) # Give threads a moment
        print("Exiting application."); self.master.destroy()


# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = BinanceTraderApp(root)
    root.mainloop()
