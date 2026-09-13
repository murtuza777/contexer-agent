import React from "react";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost";
  size?: "sm" | "md" | "lg";
  asChild?: boolean;
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: ButtonProps) {
  const baseStyles =
    "inline-flex items-center justify-center font-medium transition-all duration-150 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 disabled:opacity-50 disabled:pointer-events-none cursor-pointer select-none";

  const sizeStyles = {
    sm: "text-xs px-3 py-1.5 gap-1.5 h-8",
    md: "text-sm px-4 py-2 gap-2 h-10",
    lg: "text-base px-5 py-2.5 gap-2.5 h-12 font-semibold",
  };

  const variantStyles = {
    primary:
      "bg-zinc-100 text-zinc-950 hover:bg-white hover:shadow-[0_0_20px_rgba(255,255,255,0.2)] active:scale-[0.98] border border-transparent",
    secondary:
      "bg-zinc-900 text-zinc-200 hover:bg-zinc-800 border border-zinc-800 hover:border-zinc-700 active:scale-[0.98]",
    outline:
      "bg-transparent text-zinc-300 hover:text-zinc-100 border border-zinc-800 hover:border-zinc-600 hover:bg-zinc-900/50 active:scale-[0.98]",
    ghost:
      "bg-transparent text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900/60 active:scale-[0.98]",
  };

  return (
    <button
      className={`${baseStyles} ${sizeStyles[size]} ${variantStyles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
