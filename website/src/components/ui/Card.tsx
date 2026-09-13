import React from "react";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "terminal" | "glow" | "subtle";
  children: React.ReactNode;
}

export function Card({
  variant = "default",
  className = "",
  children,
  ...props
}: CardProps) {
  const variantStyles = {
    default:
      "bg-zinc-900/60 border border-zinc-800/80 rounded-xl backdrop-blur-sm shadow-sm",
    terminal:
      "bg-[#0d0e12] border border-zinc-800/90 rounded-xl font-mono shadow-2xl overflow-hidden",
    glow:
      "bg-zinc-900/50 border border-zinc-800 rounded-xl relative overflow-hidden before:absolute before:inset-0 before:bg-gradient-to-b before:from-zinc-800/20 before:to-transparent before:pointer-events-none",
    subtle:
      "bg-zinc-950/40 border border-zinc-900/80 rounded-xl",
  };

  return (
    <div
      className={`${variantStyles[variant]} transition-all duration-200 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
