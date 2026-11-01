import * as React from "react";
import { Link } from "react-router-dom";
import { BookOpen, Check, ChevronDown, Eye, Plus } from "lucide-react";

import { cn } from "@/lib/utils";
import { pushLayer } from "@/lib/layers";
import { RoleBadge } from "@/components/ui/role-badge";
import { usePreview } from "@/contexts/PreviewContext";
import { useCurrentCampaign } from "@/hooks/useCurrentCampaign";
import { useEffectiveRole, useRoleFor } from "@/hooks/useEffectiveRole";
import type { Campaign } from "@/types";

// The nav's current-Campaign menu button (E0-UX.7): campaign name plus the
// user's Role in it. WAI-ARIA menu button: one menuitemradio per campaign,
// then "Preview as Player" (GMs only, not while previewing) and "Create a
// campaign". Esc closes only the menu (a layer) and never exits preview.
//
// Roles shown here are cosmetic; the server enforces them (AD-13).

export const CREATE_CAMPAIGN_HREF = "/dashboard?new=1";

const FOCUS_RING =
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const ITEM =
  "flex min-h-11 w-full items-center gap-2 rounded-sm px-2 text-left text-sm text-foreground focus:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-4 [&_svg]:shrink-0";

export interface SwitcherMenu {
  /** "Preview as Player" is offered: real GM / Co-GM, not already previewing. */
  canPreview: boolean;
  previewIndex: number;
  createIndex: number;
  itemCount: number;
  /** The item focused on open: the checked campaign, else the first item. */
  initialIndex: number;
}

/** Menu layout: one item per campaign, then Preview (if offered), then Create. */
export function switcherMenu({
  campaigns,
  currentId,
  realRoleIsGm,
  previewActive,
}: {
  campaigns: readonly Pick<Campaign, "id">[];
  currentId: string | null;
  realRoleIsGm: boolean;
  previewActive: boolean;
}): SwitcherMenu {
  const canPreview = currentId !== null && realRoleIsGm && !previewActive;
  const createIndex = campaigns.length + (canPreview ? 1 : 0);
  const checked = currentId === null ? -1 : campaigns.findIndex((c) => c.id === currentId);
  return {
    canPreview,
    previewIndex: canPreview ? campaigns.length : -1,
    createIndex,
    itemCount: createIndex + 1,
    initialIndex: checked >= 0 ? checked : 0,
  };
}

// Each campaign's real role (one hook call per item, through the useRoleFor seam).
function CampaignRoleBadge({ campaign }: { campaign: Campaign }) {
  return <RoleBadge role={useRoleFor(campaign).role} className="shrink-0" />;
}

export function CampaignSwitcher({ className }: { className?: string }) {
  const { current, campaigns, ready, setCurrent } = useCurrentCampaign();
  const effective = useEffectiveRole();
  const realRole = useRoleFor(current);
  const preview = usePreview();

  const [open, setOpen] = React.useState(false);
  const [activeIndex, setActiveIndex] = React.useState(0);
  const wrapperRef = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const itemRefs = React.useRef<(HTMLElement | null)[]>([]);
  const menuId = React.useId();

  const { canPreview, previewIndex, createIndex, itemCount, initialIndex } = switcherMenu({
    campaigns,
    currentId: current?.id ?? null,
    realRoleIsGm: realRole.isGm,
    previewActive: preview.active,
  });

  const focusTrigger = () => triggerRef.current?.focus();

  const openMenu = (index?: number) => {
    setActiveIndex(index ?? initialIndex);
    setOpen(true);
  };

  const closeMenu = (returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) focusTrigger();
  };

  // Focus follows the active item.
  React.useEffect(() => {
    if (open) itemRefs.current[activeIndex]?.focus();
  }, [open, activeIndex]);

  // Esc closes the menu and returns focus to the trigger; as a layer it stays
  // below any SlideOver's handling and never reaches the preview.
  React.useEffect(() => {
    if (!open) return;
    return pushLayer(() => closeMenu(true));
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const onWrapperBlur = (event: React.FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget as Node | null;
    if (next && !event.currentTarget.contains(next)) setOpen(false);
  };

  const onTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openMenu();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      openMenu(itemCount - 1);
    }
  };

  const onMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setActiveIndex((i) => (i + 1) % itemCount);
        break;
      case "ArrowUp":
        event.preventDefault();
        setActiveIndex((i) => (i - 1 + itemCount) % itemCount);
        break;
      case "Home":
        event.preventDefault();
        setActiveIndex(0);
        break;
      case "End":
        event.preventDefault();
        setActiveIndex(itemCount - 1);
        break;
      case "Tab":
        // Focus the trigger first so the browser's Tab moves on from it.
        focusTrigger();
        setOpen(false);
        break;
      // Enter and Space activate the focused item through its click.
    }
  };

  const itemProps = (index: number) => ({
    ref: (el: HTMLElement | null) => {
      itemRefs.current[index] = el;
    },
    tabIndex: -1,
    onMouseMove: () => index !== activeIndex && setActiveIndex(index),
  });

  const label = current ? current.name : ready && campaigns.length === 0 ? "No campaign" : "Campaign";

  return (
    <div ref={wrapperRef} onBlur={onWrapperBlur} className={cn("relative min-w-0", className)}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => (open ? closeMenu(false) : openMenu())}
        onKeyDown={onTriggerKeyDown}
        className={cn(
          "flex min-h-11 max-w-full items-center gap-1.5 rounded-md border border-border px-2 text-sm text-foreground transition-colors hover:bg-muted/60 sm:px-3",
          FOCUS_RING
        )}
      >
        <BookOpen aria-hidden="true" className="hidden size-4 shrink-0 text-muted-foreground sm:block" />
        <span className="sr-only">Current campaign: </span>
        <span className="min-w-0 truncate sm:max-w-[12rem]">{label}</span>
        {current && (
          <>
            <span className="sr-only">, role </span>
            <RoleBadge role={effective.role} className="shrink-0" />
          </>
        )}
        <ChevronDown
          aria-hidden="true"
          className={cn("size-3 shrink-0 transition-transform", open && "rotate-180")}
        />
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Campaigns"
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 top-full z-50 mt-2 max-h-[75vh] w-[min(18rem,calc(100vw-2rem))] overflow-y-auto rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl sm:left-0 sm:right-auto"
        >
          {campaigns.length === 0 && (
            <p className="px-2 py-2 text-sm text-muted-foreground">You don't have a campaign yet.</p>
          )}
          {campaigns.map((c, index) => {
            const checked = c.id === current?.id;
            return (
              <button
                key={c.id}
                {...itemProps(index)}
                type="button"
                role="menuitemradio"
                aria-checked={checked}
                onClick={() => {
                  if (!checked) setCurrent(c);
                  closeMenu(true);
                }}
                className={ITEM}
              >
                <span className="flex size-4 shrink-0 items-center justify-center">
                  {checked ? <Check aria-hidden="true" /> : null}
                </span>
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                <span className="sr-only">, role </span>
                <CampaignRoleBadge campaign={c} />
              </button>
            );
          })}

          <div role="separator" className="my-1 h-px bg-border" />

          {canPreview && current && (
            <button
              {...itemProps(previewIndex)}
              type="button"
              role="menuitem"
              onClick={() => {
                preview.enter(current.id);
                closeMenu(true);
              }}
              className={ITEM}
            >
              <Eye aria-hidden="true" className="text-muted-foreground" />
              Preview as Player
            </button>
          )}

          <Link
            {...itemProps(createIndex)}
            to={CREATE_CAMPAIGN_HREF}
            role="menuitem"
            onClick={() => setOpen(false)}
            className={ITEM}
          >
            <Plus aria-hidden="true" className="text-muted-foreground" />
            Create a campaign
          </Link>
        </div>
      )}
    </div>
  );
}
