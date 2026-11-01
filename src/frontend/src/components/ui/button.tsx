import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"
import { useWriteGuard } from "@/contexts/PreviewContext"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline:
          "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  /**
   * Marks a button that writes data. While "Preview as Player" is on it is
   * disabled with the title "Preview is read-only". Cosmetic only: the server
   * still enforces access (AD-13).
   */
  write?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild = false, write = false, disabled, title, ...props },
    ref
  ) => {
    const Comp = asChild ? Slot : "button"
    const guard = useWriteGuard()
    const blocked = write && guard.disabled
    // A blocked button keeps pointer events so its title shows on hover.
    // With asChild (a link) `disabled` does nothing, so also stop the click.
    // The capture handler runs before the child's own onClick (Slot merges
    // bubble handlers with the child's first).
    const stop = (event: React.SyntheticEvent) => {
      event.preventDefault()
      event.stopPropagation()
    }
    const blockedChildProps =
      blocked && asChild
        ? { "aria-disabled": true, tabIndex: -1, onClick: stop, onClickCapture: stop }
        : {}
    return (
      <Comp
        className={cn(
          buttonVariants({ variant, size, className }),
          blocked && "disabled:pointer-events-auto cursor-not-allowed"
        )}
        ref={ref}
        disabled={blocked || disabled}
        title={blocked ? guard.title : title}
        {...props}
        {...blockedChildProps}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
