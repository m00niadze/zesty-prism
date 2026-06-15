import { useEffect, useRef, useState } from "react";
import { ArbOpportunity, fetchOpportunities } from "../api/client";

export function useArb(liveOnly: boolean, minPct: number, intervalMs = 5000) {
  const [data, setData] = useState<ArbOpportunity[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = async () => {
    try {
      const res = await fetchOpportunities(liveOnly, minPct);
      setData(res.data.items);
      setTotal(res.data.total);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, intervalMs);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [liveOnly, minPct]);

  return { data, total, loading, error, refetch: load };
}
