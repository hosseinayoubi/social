"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/components/api";

export default function Home() {
  const r = useRouter();
  useEffect(() => {
    const t = getToken();
    r.replace(t ? "/dashboard" : "/login");
  }, [r]);
  return null;
}
