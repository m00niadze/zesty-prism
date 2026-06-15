import { useEffect, useState } from "react";
import { fetchFeesSummary, fetchPnlSummary } from "../api/client";

export function usePnl() {
  const [pnl, setPnl] = useState({ unrealized_pnl: 0, realized_pnl: 0, total_fees_paid: 0, net_pnl: 0 });
  const [fees, setFees] = useState({ polymarket_fees: 0, predictfun_fees: 0, total_fees: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [pnlRes, feesRes] = await Promise.all([fetchPnlSummary(), fetchFeesSummary()]);
        setPnl(pnlRes.data);
        setFees(feesRes.data);
      } finally {
        setLoading(false);
      }
    };
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  return { pnl, fees, loading };
}
