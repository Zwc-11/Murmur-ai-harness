import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from "react";

const ReducedMotionContext = createContext(false);

export function ReducedMotionProvider({ children }: { children: ReactNode }) {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return createElement(ReducedMotionContext.Provider, { value: reduced }, children);
}

export function useReducedMotion(): boolean {
  return useContext(ReducedMotionContext);
}
