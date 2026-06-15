import { useEffect, useRef, useState } from "react";
import { CalculatorData, fetchCalculator } from "../api/client";

// Fetches the live order-book ladders for one opportunity and re-polls while the
// drawer is open. Returns null id → idle (drawer closed).
export function useCalculator(opportunityId: number | null, intervalMs = 4000) {
  const [data, setData] = useState<CalculatorData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (opportunityId == null) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);

    const load = async () => {
      try {
        const res = await fetchCalculator(opportunityId);
        if (!cancelled) {
          setData(res.data);
          setError(null);
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.response?.status === 404 ? "Opportunity is no longer live." : e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    timerRef.current = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [opportunityId, intervalMs]);

  return { data, loading, error };
}
