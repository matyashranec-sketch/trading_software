import { animate } from "framer-motion";
import { useEffect, useRef, useState } from "react";

/** Smoothly animates a number from its previous value to the new one. */
export default function CountUp({
  value,
  format,
  duration = 0.9,
}: {
  value: number;
  format: (n: number) => string;
  duration?: number;
}) {
  const [display, setDisplay] = useState(value);
  const from = useRef(0);

  useEffect(() => {
    const controls = animate(from.current, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setDisplay(v),
    });
    from.current = value;
    return () => controls.stop();
  }, [value, duration]);

  return <>{format(display)}</>;
}
