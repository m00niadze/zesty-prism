import { useCallback, useEffect, useRef, useState } from "react";
import { PortfolioSummary, fetchPortfolioSummary } from "../api/client";

const EMPTY: PortfolioSummary = {
  stats: { open_ev: 0, deployed: 0, max_payoff: 0, active_pairs: 0 },
  pairs: [],
  closing: [],
  standalone: [],
};

export function usePortfolioSummary(intervalMs = 8000) {
  const [data, setData] = useState<PortfolioSummary>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetchPortfolioSummary();
      setData(res.data);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    timer.current = setInterval(load, intervalMs);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load, intervalMs]);

  return { data, loading, error, reload: load };
}
