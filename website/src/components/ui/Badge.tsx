import React from "react";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "success" | "warning" | "danger" | "cyan" | "outline";
  children: React.ReactNode;
}

export function Badge({
  variant = "default",
  className = "",
  children,
  ...props
}: BadgeProps) {
  const variantStyles = {
    default: "bg-zinc-800/80 text-zinc-300 border-zinc-700/60",
    success: "bg-emerald-950/60 text-emerald-400 border-emerald-800/60",
    warning: "bg-amber-950/60 text-amber-400 border-amber-800/60",
    danger: "bg-rose-950/60 text-rose-400 border-rose-800/60",
    cyan: "bg-cyan-950/60 text-cyan-400 border-cyan-800/60",
    outline: "bg-transparent text-zinc-400 border-zinc-800",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-mono font-medium border tracking-wide transition-colors ${variantStyles[variant]} ${className}`}
      {...props}
    >
      {children}
    </span>
  );
}
