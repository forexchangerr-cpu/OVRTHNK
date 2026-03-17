import json
import os
import sys


def out(data: dict):
    print(json.dumps(data, ensure_ascii=False))


try:
    import MetaTrader5 as mt5
except Exception as e:
    out({"ok": False, "error": f"MetaTrader5 import failed: {e}"})
    raise SystemExit(0)


def env_bool(name: str, default: bool = False):
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def initialize_mt5():
    mt5_path = os.getenv("MT5_PATH", "").strip()
    mt5_login = os.getenv("MT5_LOGIN", "").strip()
    mt5_password = os.getenv("MT5_PASSWORD", "").strip()
    mt5_server = os.getenv("MT5_SERVER", "").strip()

    if mt5_path:
        ok = mt5.initialize(path=mt5_path)
    else:
        ok = mt5.initialize()
    if not ok:
        return False, f"initialize failed: {mt5.last_error()}"

    if mt5_login and mt5_password and mt5_server:
        login_ok = mt5.login(login=int(mt5_login), password=mt5_password, server=mt5_server)
        if not login_ok:
            return False, f"login failed: {mt5.last_error()}"

    return True, "ok"


def account_info():
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "login": int(info.login),
        "server": str(info.server),
        "balance": float(info.balance),
        "equity": float(info.equity),
        "margin": float(info.margin),
        "currency": str(info.currency),
    }


def send_order(payload: dict):
    symbol = str(payload.get("symbol", "")).upper().strip()
    side = str(payload.get("side", "")).lower().strip()
    lot = float(payload.get("lot", 0.0))
    sl = float(payload.get("sl", 0.0))
    tp = float(payload.get("tp", 0.0))
    comment = str(payload.get("comment", "ovrthnk-bridge"))[:30]

    if not symbol or side not in {"buy", "sell"} or lot <= 0 or sl <= 0 or tp <= 0:
        return {"ok": False, "error": "invalid order payload"}

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return {"ok": False, "error": f"symbol not found: {symbol}"}
    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"ok": False, "error": f"tick unavailable: {symbol}"}

    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    price = tick.ask if side == "buy" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 20260317,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        return {"ok": False, "error": f"order_send returned None: {mt5.last_error()}"}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {
            "ok": False,
            "error": f"retcode={result.retcode}",
            "comment": getattr(result, "comment", ""),
        }

    return {
        "ok": True,
        "ticket": int(result.order),
        "deal": int(getattr(result, "deal", 0)),
        "retcode": int(result.retcode),
    }


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "ping"
    payload = {}
    if len(sys.argv) > 2:
        try:
            payload = json.loads(sys.argv[2])
        except Exception:
            payload = {}

    ok, msg = initialize_mt5()
    if not ok:
        out({"ok": False, "error": msg})
        return

    try:
        if action == "ping":
            acc = account_info()
            if not acc:
                out({"ok": False, "error": "account_info unavailable"})
            else:
                out({"ok": True, "account": acc})
            return

        if action == "account_info":
            acc = account_info()
            if not acc:
                out({"ok": False, "error": "account_info unavailable"})
            else:
                out({"ok": True, "account": acc})
            return

        if action == "send_order":
            res = send_order(payload)
            out(res)
            return

        out({"ok": False, "error": f"unknown action: {action}"})
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
