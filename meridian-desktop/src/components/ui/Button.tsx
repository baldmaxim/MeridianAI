import React from "react";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:
    | "primary"
    | "primary-soft"
    | "secondary"
    | "warning"
    | "danger"
    | "danger-ghost"
    | "ghost";
  size?: "sm" | "md" | "lg";
}

export const Button: React.FC<ButtonProps> = ({
  children,
  className = "",
  variant = "primary",
  size = "md",
  ...props
}) => {
  const baseClasses =
    "font-medium rounded-[10px] border focus:outline-none transition-colors duration-200 motion-reduce:transition-none disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer";

  const variantClasses = {
    primary:
      "text-on-accent bg-logo-primary border-logo-primary hover:bg-logo-primary/85 hover:border-logo-primary/85 focus:ring-1 focus:ring-logo-primary",
    "primary-soft":
      "text-text bg-logo-primary/20 border-transparent hover:bg-logo-primary/30 focus:ring-1 focus:ring-logo-primary",
    secondary:
      "text-text bg-transparent border-border hover:bg-elevated hover:border-logo-primary/60 focus:ring-1 focus:ring-logo-primary",
    // Secondary's neutral resting look, but hover/focus use the semantic
    // --color-warning token (theme.css) instead of the pink accent — for
    // buttons sitting on warning surfaces like SecureInputWarning
    warning:
      "text-text bg-mid-gray/10 border-mid-gray/20 hover:bg-warning/15 hover:border-warning focus:ring-1 focus:ring-warning",
    danger:
      "text-on-error bg-error border-mid-gray/20 hover:bg-error/85 hover:border-error/85 focus:ring-1 focus:ring-error",
    "danger-ghost":
      "text-error border-transparent hover:bg-error/10 focus:bg-error/20",
    ghost:
      "text-current border-transparent hover:bg-mid-gray/10 hover:border-logo-primary focus:bg-mid-gray/20",
  };

  const sizeClasses = {
    sm: "px-2 py-1 text-xs",
    md: "px-4 py-[5px] text-sm",
    lg: "px-4 py-2 text-base",
  };

  return (
    <button
      className={`${baseClasses} ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
};
