#property strict
#property version   "1.01"
#property description "OVRTHNK file bridge EA"

#include <Trade/Trade.mqh>
CTrade trade;

string OUTBOX_FILE = "ovrthnk_orders_outbox.csv";
string RESULT_FILE = "ovrthnk_orders_result.csv";
string PROCESSED_FILE = "ovrthnk_processed_ids.txt";
string ACCOUNT_STATE_FILE = "ovrthnk_account_state.csv";
string SYMBOL_REQUEST_FILE = "ovrthnk_symbol_request.txt";
string SYMBOL_INFO_FILE = "ovrthnk_symbol_info.csv";

string processed_ids[];

string TrimText(string s)
{
   StringTrimLeft(s);
   StringTrimRight(s);
   return s;
}

bool IsProcessed(const string id)
{
   for(int i=0;i<ArraySize(processed_ids);i++)
      if(processed_ids[i]==id) return true;
   return false;
}

void AddProcessed(const string id)
{
   int n = ArraySize(processed_ids);
   ArrayResize(processed_ids, n+1);
   processed_ids[n] = id;

   int f = FileOpen(PROCESSED_FILE, FILE_TXT|FILE_READ|FILE_WRITE|FILE_COMMON|FILE_ANSI);
   if(f != INVALID_HANDLE)
   {
      FileSeek(f, 0, SEEK_END);
      FileWriteString(f, id + "\n");
      FileClose(f);
   }
}

void LoadProcessed()
{
   ArrayResize(processed_ids, 0);
   int f = FileOpen(PROCESSED_FILE, FILE_TXT|FILE_READ|FILE_COMMON|FILE_ANSI);
   if(f == INVALID_HANDLE) return;

   while(!FileIsEnding(f))
   {
      string line = TrimText(FileReadString(f));
      if(line == "") continue;
      int n = ArraySize(processed_ids);
      ArrayResize(processed_ids, n+1);
      processed_ids[n] = line;
   }
   FileClose(f);
}

void AppendResult(string id, string status, string ticket, string note)
{
   bool exists = FileIsExist(RESULT_FILE, FILE_COMMON);
   int f = FileOpen(RESULT_FILE, FILE_CSV|FILE_READ|FILE_WRITE|FILE_COMMON|FILE_ANSI, ',');
   if(f == INVALID_HANDLE) return;

   FileSeek(f, 0, SEEK_END);
   if(!exists || FileSize(f) == 0)
      FileWrite(f, "id", "status", "ticket", "note", "updated_at");

   FileWrite(f, id, status, ticket, note, TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS));
   FileClose(f);
}

bool ProcessOneOrder(string id, string symbol, string side, double lot, double sl, double tp, string comment)
{
   if(!SymbolSelect(symbol, true))
   {
      AppendResult(id, "failed", "", "symbol_select_failed");
      AddProcessed(id);
      return false;
   }

   bool ok=false;
   if(side == "buy")
      ok = trade.Buy(lot, symbol, 0.0, sl, tp, comment);
   else if(side == "sell")
      ok = trade.Sell(lot, symbol, 0.0, sl, tp, comment);
   else
   {
      AppendResult(id, "failed", "", "invalid_side:" + side);
      Print("OVRTHNKBridgeEA v1.01 invalid side for id=", id, " raw_side=[", side, "] symbol=", symbol);
      AddProcessed(id);
      return false;
   }

   if(ok)
   {
      ulong ticket = trade.ResultOrder();
      AppendResult(id, "filled", (string)ticket, "ok");
      AddProcessed(id);
      return true;
   }
   else
   {
      string note = "retcode=" + (string)trade.ResultRetcode();
      AppendResult(id, "failed", "", note);
      AddProcessed(id);
      return false;
   }
}

void PollOutbox()
{
   int f = FileOpen(OUTBOX_FILE, FILE_CSV|FILE_READ|FILE_COMMON|FILE_ANSI, ',');
   if(f == INVALID_HANDLE) return;

   bool header_read = false;
   while(!FileIsEnding(f))
   {
      string id = FileReadString(f);
      string created_at = FileReadString(f);
      string symbol = FileReadString(f);
      string side = FileReadString(f);
      string lot_s = FileReadString(f);
      string sl_s = FileReadString(f);
      string tp_s = FileReadString(f);
      string comment = FileReadString(f);

      id = TrimText(id);
      created_at = TrimText(created_at);
      symbol = TrimText(symbol);
      StringToUpper(symbol);
      side = TrimText(side);
      StringToLower(side);
      lot_s = TrimText(lot_s);
      sl_s = TrimText(sl_s);
      tp_s = TrimText(tp_s);
      comment = TrimText(comment);

      if(!header_read)
      {
         header_read = true;
         string id_lower = id;
         StringToLower(id_lower);
         if(id_lower == "id") continue;
      }

      if(id == "") continue;
      if(IsProcessed(id)) continue;

      double lot = StringToDouble(lot_s);
      double sl = StringToDouble(sl_s);
      double tp = StringToDouble(tp_s);

      ProcessOneOrder(id, symbol, side, lot, sl, tp, comment);
   }
   FileClose(f);
}

int OnInit()
{
   LoadProcessed();
   EventSetTimer(5);
   Print("OVRTHNKBridgeEA v1.01 started.");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void WriteAccountState()
{
   int f = FileOpen(ACCOUNT_STATE_FILE, FILE_CSV|FILE_WRITE|FILE_COMMON|FILE_ANSI, ',');
   if(f == INVALID_HANDLE) return;
   FileWrite(f, "balance", "equity", "profit", "margin_free", "updated_at");
   FileWrite(f,
      DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2),
      DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2),
      DoubleToString(AccountInfoDouble(ACCOUNT_PROFIT), 2),
      DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2),
      TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS)
   );
   FileClose(f);
}

void HandleSymbolInfoRequest()
{
   if(!FileIsExist(SYMBOL_REQUEST_FILE, FILE_COMMON)) return;

   int rf = FileOpen(SYMBOL_REQUEST_FILE, FILE_TXT|FILE_READ|FILE_COMMON|FILE_ANSI);
   if(rf == INVALID_HANDLE) return;
   string symbol = TrimText(FileReadString(rf));
   FileClose(rf);
   FileDelete(SYMBOL_REQUEST_FILE, FILE_COMMON);
   if(symbol == "") return;

   if(!SymbolSelect(symbol, true))
   {
      int wf2 = FileOpen(SYMBOL_INFO_FILE, FILE_CSV|FILE_WRITE|FILE_COMMON|FILE_ANSI, ',');
      if(wf2 != INVALID_HANDLE)
      {
         FileWrite(wf2, "symbol","spread","contract_size","min_lot","max_lot","lot_step","digits","tick_value","tick_size","bid","ask");
         FileWrite(wf2, symbol,"0","0","0","0","0","0","0","0","0","0");
         FileClose(wf2);
      }
      return;
   }

   int wf = FileOpen(SYMBOL_INFO_FILE, FILE_CSV|FILE_WRITE|FILE_COMMON|FILE_ANSI, ',');
   if(wf == INVALID_HANDLE) return;
   FileWrite(wf, "symbol","spread","contract_size","min_lot","max_lot","lot_step","digits","tick_value","tick_size","bid","ask");
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   FileWrite(wf,
      symbol,
      IntegerToString((int)SymbolInfoInteger(symbol, SYMBOL_SPREAD)),
      DoubleToString(SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE), 2),
      DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN), 8),
      DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX), 2),
      DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP), 8),
      IntegerToString(digits),
      DoubleToString(SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE), 8),
      DoubleToString(SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE), 8),
      DoubleToString(SymbolInfoDouble(symbol, SYMBOL_BID), digits),
      DoubleToString(SymbolInfoDouble(symbol, SYMBOL_ASK), digits)
   );
   FileClose(wf);
}

void OnTimer()
{
   WriteAccountState();
   HandleSymbolInfoRequest();
   PollOutbox();
}
