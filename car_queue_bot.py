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
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

def get_updates():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
        return res.get("result", [])
    except:
        return []

def clear_updates(last_update_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"offset": last_update_id + 1}
    try:
        requests.get(url, params=params, timeout=10)
    except:
        pass

def backtest_car_stock(symbol_input, lot_size=5000, target_pct=0.0628):
    ticker = symbol_input.upper().replace('NSE:', '').replace('BSE:', '').strip()
    if not ticker.endswith('.NS') and not ticker.endswith('.BO'):
        ticker += '.NS'

    df = yf.download(ticker, period='2y', interval='1d', progress=False)
    if df.empty or len(df) < 100:
        return f"❌ '{symbol_input}' માટે પૂરતો ઐતિહાસિક ડેટા મળ્યો નથી. કૃપા કરીને સાચો સ્ટોક સિમ્બોલ આપો."

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 1. Year High
    df['Year_High'] = df['High'].rolling(window=250, min_periods=50).max()

    # 2. Cumulative Average from Year High
    df['High_Reset'] = df['High'] == df['Year_High']
    df['High_Group'] = df['High_Reset'].cumsum()
    df['Cumulative_Avg'] = df.groupby('High_Group')['Close'].expanding().mean().reset_index(level=0, drop=True)

    # 3. CAR Positive: 10 દિવસથી સતત વધારો
    df['Avg_Diff'] = df['Cumulative_Avg'].diff()
    df['CAR_Positive'] = (df['Avg_Diff'] > 0).rolling(window=10).apply(lambda s: (s == True).all(), raw=True).fillna(0).astype(bool)

    # 4. Weekly High (પાછલા સપ્તાહનો હાઇ)
    weekly_high = df['High'].resample('W').max().shift(1)
    df['Prev_Week_High'] = weekly_high.reindex(df.index, method='ffill')

    # છેલ્લા ૧ વર્ષનો ડેટા (આશરે ૨૫૦ દિવસ)
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
                completed_trades.append({'profit': profit})
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
    msg += f"⚙️ _CAR Positive + Weekly High GTT Trigger (Mahesh Kaushik Strategy)_"
    return msg

def main():
    updates = get_updates()
    if not updates:
        print("કોઈ નવો મેસેજ નથી.")
        return

    last_update_id = updates[-1]["update_id"]

    for u in updates:
        message = u.get("message", {})
        sender_id = message.get("from", {}).get("id")
        text = message.get("text", "").strip()

        if sender_id == ALLOWED_USER_ID and text:
            if text.startswith("/start"):
                send_telegram_msg(sender_id, "નમસ્તે અલ્પેશભાઈ! 🙏\nતમે મને કોઈપણ સ્ટોકનું નામ મોકલો (દા.ત. `TCS`, `NSE:TCS`, `PERSISTENT`). હું તરત જ ગણતરી કરી આપીશ.")
            else:
                # ૧. તાત્કાલિક સ્વીકૃતિ મેસેજ (Acknowledgment)
                ack_text = f"📩 *નિવેદન મળ્યું છે:* `{text}`\n⏳ ઐતિહાસિક ડેટા ફેચ થઈ રહ્યો છે અને CAR બેકટેસ્ટિંગ શરૂ કરી દીધું છે. કૃપા કરીને થોડી સેકન્ડ રાહ જુઓ..."
                send_telegram_msg(sender_id, ack_text)

                # ૨. ગણતરી અને રિપોર્ટ મોકલવો
                report = backtest_car_stock(text)
                send_telegram_msg(sender_id, report)

    # પ્રોસેસ થયેલા મેસેજ સાફ કરો
    clear_updates(last_update_id)

if __name__ == "__main__":
    main()
