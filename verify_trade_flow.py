import json
import time
from pathlib import Path

import main


def run_once():
    connected_now = main.mt5_baglan()
    print("MT5_CONNECT_ATTEMPT", connected_now)
    print("FLAGS", {
        "connected": main.MT5_CONNECTED,
        "backend": main.MT5_BACKEND,
        "live": main.LIVE_ORDER_EXECUTION,
        "mode": main.TRADE_EXECUTION_MODE,
    })

    if not main.MT5_CONNECTED:
        print("MT5_NOT_CONNECTED_ABORT")
        return 4

    main.trade_emir_yurutucu()
    print("QUEUE_BEFORE")
    print(main.trade_kuyruk_ozeti(10))

    symbols = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]
    created = None

    for sym in symbols:
        if sym == "XAUUSD":
            order = {"symbol": sym, "side": "buy", "lot": 0.01, "sl": 4985.0, "tp": 5038.0}
        else:
            order = {"symbol": sym, "side": "buy", "lot": 0.01, "sl": 1.0, "tp": 2.0}

        kayit, err = main.trade_emri_ekle(order, source="manual_test")
        if err:
            print(f"ADD_ERR_{sym}", err)
            continue

        created = kayit
        print("ADDED", created["id"], sym, created["status"])
        if created.get("status") == "pending_approval":
            ok, msg = main.trade_emri_onayla(created["id"])
            print("APPROVE", ok, msg)
            if not ok:
                return 3
        else:
            print("APPROVE", True, f"skip ({created.get('status')})")
        main.trade_emir_yurutucu()
        break

    if not created:
        print("NO_ORDER_CREATED")
        return 2

    final = None
    for i in range(12):
        time.sleep(5)
        main.trade_emir_yurutucu()
        q = main.trade_queue_yukle().get("orders", [])
        hit = next((o for o in q if o.get("id") == created["id"]), None)
        if not hit:
            continue
        st = hit.get("status")
        note = hit.get("mt5_note") or hit.get("error")
        print(f"POLL {i+1}: status={st} note={note}")
        if st in {"filled", "open", "failed", "rejected", "closed"}:
            final = hit
            break

    q = main.trade_queue_yukle().get("orders", [])
    final = final or next((o for o in q if o.get("id") == created["id"]), None)
    print("FINAL", json.dumps(final, ensure_ascii=False))

    res = Path(main.mt5_result_file())
    out = Path(main.mt5_outbox_file())
    print("RESULT_PATH", res)
    print("RESULT_EXISTS", res.exists())
    if res.exists():
        print("RESULT_LAST_10")
        for line in res.read_text(encoding="utf-8", errors="ignore").splitlines()[-10:]:
            print(line)

    print("OUTBOX_PATH", out)
    print("OUTBOX_EXISTS", out.exists())
    if out.exists():
        print("OUTBOX_LAST_10")
        for line in out.read_text(encoding="utf-8", errors="ignore").splitlines()[-10:]:
            print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_once())
