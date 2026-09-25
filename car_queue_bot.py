import os
import requests
import yfinance as yf
import pandas as pd
import numpy as np

BOT_TOKEN = "8896031421:AAFIeqDTKsH64aAnaCuiuW8F9aZxMTIEA9g"
ALLOWED_USER_ID = 583221734

def send_telegram_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def get_latest_messages():
    """ટેલિગ્રામમાંથી નવા વણવંચાયેલા મેસેજ ખેંચવા"""
    # છેલ્લે પ્રોસેસ થયેલું update_id સાચવવા
    offset = None
    if os.path.exists("last_offset.txt"):
        with open("last_offset.txt", "r") as f:
            try:
                offset = int(f.read().strip()) + 1
            except:
                offset = None

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 5}
    if offset:
        params["offset"] = offset

    res = requests.get(url, params=params).json()
    updates = res.get("result", [])
    return updates

def update_offset(last_id):
    with open("last_offset.txt", "w") as f:
        f.write(str(last_id))

def backtest_car_stock(symbol_input, lot_size=5000, target_pct=0.0628):
    ticker = symbol_input.upper().replace('NSE:', '').replace('BSE:', '').strip()
    if not ticker.endswith('.NS') and not ticker.endswith('.BO'):
        ticker += '.NS'

    df = yf.download(ticker, period='2y', interval='1d', progress=False)
    if df.empty or len(df) < 100:
        return f"❌ '{symbol_input}' માટે ડેટા મળ્યો નથી. સાચો સિમ્બોલ આપો."

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 1. Year High
    df['Year_High'] = df['High'].rolling(window=250, min_periods=50).max()

    # 2. Cumulative Average
    df['High_Reset'] = df['High'] == df['Year_High']
    df['High_Group'] = df['High_Reset'].cumsum()
    df['Cumulative_Avg'] = df.groupby('High_Group')['Close'].expanding().mean().reset_index(level=0, drop=True)

    # 3. CAR Positive
    df['Avg_Diff'] = df['Cumulative_Avg'].diff()
    df['CAR_Positive'] = (df['Avg_Diff'] > 0).rolling(window=10).apply(lambda s: (s == True).all(), raw=True).fillna(0).astype(bool)

    # 4. Weekly High
    weekly_high = df['High'].resample('W').max().shift(1)
    df['Prev_Week_High'] = weekly_high.reindex(df.index, method='ffill')

    # છેલ્લા ૧ વર્ષ (૨૫૦ દિવસ)
    backtest_df = df.iloc[-250:].copy()
    open_lots = []
    completed_trades = []

    for date, row in backtest_df.iterrows():
        # Target Check (6.28%)
        remaining_lots = []
        for lot in open_lots:
            target_price = lot['buy_price'] * (1 + target_pct)
            if row['High'] >= target_price:
                profit = lot['qty'] * (target_price - lot['buy_price'])
                completed_trades.append({
                    'profit': profit
                })
            else:
                remaining_lots.append(lot)
        open_lots = remaining_lots

        # GTT Buy Trigger
        if row['CAR_Positive'] and not pd.isna(row['Prev_Week_High']):
            trigger_price = row['Prev_Week_High']
            if row['High'] >= trigger_price:
                exec_price = max(trigger_price, row['Open'])
                qty = int(lot_size // exec_price)
                if qty > 0:
                    open_lots.append({
                        'buy_date': date,
                        'buy_price': exec_price,
                        'qty': qty
                    })

    cmp = float(backtest_df['Close'].iloc[-1])
    total_booked_profit = sum(t['profit'] for t in completed_trades)

    msg = f"📊 *બેકટેસ્ટ રિપોર્ટ: {ticker.replace('.NS', '')}* (છેલ્લા ૧ વર્ષ)\n"
    msg += f"──────────────────────\n"
    msg += f"🔹 *વર્તમાન કિંમત (CMP):* ₹{cmp:,.2f}\n"
    msg += f"✅ *સફળ ટ્રેડ્સ (Target 6.28%):* {len(completed_trades)} વાર\n"
    msg += f"💰 *કુલ બુક થયેલો નફો:* ₹{total_booked_profit:,.2f}\n\n"

    msg += f"📦 *ચાલુ હોલ્ડિંગ સ્થિતિ:*\n"
    if len(open_lots) == 0:
        msg += f"🎉 *કોઈ લોટ બાકી નથી!* તમામ ખરીદાયેલા લોટ 6.28% ના ટાર્ગેટ સાથે વેચાઈ ગયા છે.\n"
    else:
        total_open_qty = sum(l['qty'] for l in open_lots)
        total_open_inv = sum(l['qty'] * l['buy_price'] for l in open_lots)
        avg_price = total_open_inv / total_open_qty
        last_lot = open_lots[-1]
        current_val = total_open_qty * cmp
        unrealized_pnl = current_val - total_open_inv
        unrealized_pnl_pct = (unrealized_pnl / total_open_inv) * 100

        msg += f"• *ઊભા રહેલા ₹૫,૦૦૦ ના લોટ્સ:* {len(open_lots)}\n"
        msg += f"• *કુલ બાકી શેર:* {total_open_qty}\n"
        msg += f"• *ખરીદ સરેરાશ (Average):* ₹{avg_price:,.2f}\n"
        msg += f"• *છેલ્લા લોટની કિંમત:* ₹{last_lot['buy_price']:,.2f} ({last_lot['buy_date'].strftime('%d-%m-%Y')})\n"
        msg += f"• *કુલ રોકાણ:* ₹{total_open_inv:,.2f}\n"
        pnl_sign = "+" if unrealized_pnl >= 0 else ""
        msg += f"• *હાલનું P&L:* {pnl_sign}₹{unrealized_pnl:,.2f} ({pnl_sign}{unrealized_pnl_pct:.2f}%)\n"

    msg += f"──────────────────────\n"
    msg += f"⚙️ _CAR Positive (10 Days) + Weekly High GTT Trigger_"
    return msg

def main():
    updates = get_latest_messages()
    if not updates:
        print("કોઈ નવો મેસેજ નથી. સ્ક્રિપ્ટ પૂર્ણ થઈ.")
        return

    last_id = None
    for u in updates:
        last_id = u["update_id"]
        message = u.get("message", {})
        sender_id = message.get("from", {}).get("id")
        text = message.get("text", "").strip()

        # ફક્ત અલ્પેશભાઈના મેસેજનો જ જવાબ આપવો
        if sender_id == ALLOWED_USER_ID and text:
            if text.startswith("/start"):
                send_telegram_msg(sender_id, "નમસ્તે અલ્પેશભાઈ! 🙏 સ્ટોકનું નામ લખીને મોકલો (દા.ત. TCS, PERSISTENT). આગળના રનમાં તમને રિપોર્ટ મળી જશે.")
            else:
                send_telegram_msg(sender_id, f"⏳ `{text}` માટે બેકટેસ્ટિંગ શરૂ થઈ રહ્યું છે...")
                report = backtest_car_stock(text)
                send_telegram_msg(sender_id, report)

    if last_id:
        update_offset(last_id)

if __name__ == "__main__":
    main()
