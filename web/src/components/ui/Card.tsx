import type { CSSProperties, ReactNode } from "react";

/** Flat surface with a hairline border. No blur, glow, or motion. */
export default function Card({
  children,
  className = "",
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div className={`card ${className}`} style={style}>
      {children}
    </div>
  );
}
