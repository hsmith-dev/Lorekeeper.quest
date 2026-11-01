import { useState, useRef, useEffect, useId } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ThemeSelector } from "./ThemeSelector";
import { CampaignSwitcher } from "./shell/CampaignSwitcher";
import { uploadAvatar, getMe } from "../services/api";
import { setPreviewCampaignId } from "@/lib/preview";
import { pushLayer } from "@/lib/layers";
import { gmNavGroups, playerNav, type NavLink } from "@/lib/routes";
import { useNavAudience } from "@/hooks/useNavAudience";
import { useQuery, useQueryClient } from "@tanstack/react-query";

// The nav sets come from the route registry (lib/routes.ts, E0-UX.8): GM
// groups or the Player set by audience, each link only once its route is
// registered. Admin is a GM-set group for the configured admin only (see
// app/api/deps.py::require_admin); AdminPage also self-guards.
interface MenuGroup {
  /** null: no heading (the Player set is one short list). */
  label: string | null;
  links: NavLink[];
}

function useNavMenuGroups(isAdmin: boolean): MenuGroup[] {
  const audience = useNavAudience();
  return audience === "player" ? [{ label: null, links: playerNav() }] : gmNavGroups({ isAdmin });
}

const isActivePath = (pathname: string, to: string) => pathname === to || pathname.startsWith(`${to}/`);

// A disclosure of links: Enter/Space toggles, ArrowDown/ArrowUp/Home/End move
// between links, Esc closes and returns focus to the button, and Tab out or
// focus leaving closes. No aria-haspopup: it is not an ARIA menu.
function NavMenu({ isAdmin }: { isAdmin: boolean }) {
  const location = useLocation();
  const groups = useNavMenuGroups(isAdmin);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  const links = groups.flatMap((g) => g.links);
  // Longest match, so /portal/journal names My Journal rather than Portal.
  const current = links
    .filter((l) => isActivePath(location.pathname, l.to))
    .sort((a, b) => b.to.length - a.to.length)[0];

  const close = (returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) buttonRef.current?.focus();
  };

  // Close on navigation.
  useEffect(() => setOpen(false), [location.pathname]);

  // Esc, as a layer so it stays below any SlideOver's handling.
  useEffect(() => {
    if (!open) return;
    return pushLayer(() => close(true));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const linkEls = () => Array.from(panelRef.current?.querySelectorAll<HTMLAnchorElement>("a") ?? []);
  const focusLink = (index: number | "last") => {
    const els = linkEls();
    if (els.length === 0) return;
    els[index === "last" ? els.length - 1 : ((index % els.length) + els.length) % els.length]?.focus();
  };

  // Focus a link once the panel has rendered (opened from the keyboard).
  const pendingFocus = useRef<number | "last" | null>(null);
  useEffect(() => {
    if (!open || pendingFocus.current === null) return;
    focusLink(pendingFocus.current);
    pendingFocus.current = null;
  }, [open]);

  const onButtonKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const target = event.key === "ArrowDown" ? 0 : "last";
    if (open) focusLink(target);
    else {
      pendingFocus.current = target;
      setOpen(true);
    }
  };

  const onPanelKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const els = linkEls();
    const index = els.indexOf(document.activeElement as HTMLAnchorElement);
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusLink(index + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusLink(index === -1 ? "last" : index - 1);
        break;
      case "Home":
        event.preventDefault();
        focusLink(0);
        break;
      case "End":
        event.preventDefault();
        focusLink("last");
        break;
    }
  };

  const onWrapperBlur = (event: React.FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget as Node | null;
    if (next && !event.currentTarget.contains(next)) setOpen(false);
  };

  return (
    // Below sm the panel anchors to the (sticky) nav, not the button, so it
    // starts at the left gutter and never pushes past a 375px viewport.
    <div className="sm:relative" ref={wrapperRef} onBlur={onWrapperBlur}>
      {/* Icon-only below sm so the switcher and avatar fit at 375px; the
          aria-label keeps the page name for screen readers. */}
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onButtonKeyDown}
        aria-label={current ? `Menu: ${current.label}` : "Menu"}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className="flex min-h-11 min-w-11 items-center justify-center gap-1.5 px-3 rounded-md text-sm text-foreground hover:bg-muted/60 transition-colors border border-border"
      >
        <svg width="15" height="15" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="shrink-0">
          <path fillRule="evenodd" clipRule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" />
        </svg>
        <span className="hidden sm:inline max-w-[10rem] truncate">{current?.label ?? "Menu"}</span>
        <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className={`hidden sm:block transition-transform shrink-0 ${open ? "rotate-180" : ""}`}>
          <path fillRule="evenodd" clipRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" />
        </svg>
      </button>
      {open && (
        <div
          id={panelId}
          ref={panelRef}
          onKeyDown={onPanelKeyDown}
          className="absolute left-4 sm:left-0 top-full mt-2 w-60 max-w-[calc(100%-2rem)] sm:max-w-none rounded-xl border border-border bg-background shadow-xl overflow-hidden z-50 py-1.5 max-h-[75vh] overflow-y-auto"
        >
          {groups.map((group, i) => (
            <div key={group.label ?? "links"} className={i > 0 ? "mt-1.5 pt-1.5 border-t border-border" : ""}>
              {group.label && (
                <p className="px-4 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
                  {group.label}
                </p>
              )}
              {group.links.map(({ to, label }) => (
                <Link
                  key={to}
                  to={to}
                  aria-current={current?.to === to ? "page" : undefined}
                  className={`block px-4 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${
                    current?.to === to
                      ? "bg-muted text-foreground font-medium"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
                  }`}
                >
                  {label}
                </Link>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Avatar({ src, name, size = 32 }: { src?: string | null; name?: string; size?: number }) {
  if (src) {
    return (
      <img
        src={src}
        alt="Avatar"
        className="rounded-full object-cover border border-border"
        style={{ width: size, height: size }}
      />
    );
  }
  const initials = (name ?? "?")
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div
      className="rounded-full bg-primary/20 text-primary flex items-center justify-center text-xs font-bold border border-border shrink-0"
      style={{ width: size, height: size, fontSize: size * 0.35 }}
    >
      {initials}
    </div>
  );
}

function ProfileDropdown({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const token = localStorage.getItem("lk_token");
  const { data: profile } = useQuery({
    queryKey: ["me"],
    queryFn: () => getMe().then((r) => r.data),
    enabled: !!token,
    staleTime: 60_000,
  });

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    setUploading(true);
    try {
      await uploadAvatar(file);
      qc.invalidateQueries({ queryKey: ["me"] });
    } finally {
      setUploading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("lk_token");
    localStorage.removeItem("lk_user");
    setPreviewCampaignId(null);
    navigate("/login");
    onClose();
  };

  return (
    <div className="flex flex-col divide-y divide-border">
      {/* User info */}
      <div className="px-4 py-3 flex items-center gap-3">
        <Avatar src={profile?.avatar_data} name={profile?.display_name} size={40} />
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-semibold text-foreground truncate">{profile?.display_name}</span>
          <span className="text-xs text-muted-foreground truncate">{profile?.email}</span>
        </div>
      </div>

      {/* Avatar upload + Settings */}
      <div className="px-2 py-2 flex flex-col gap-0.5">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
        >
          {uploading ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin shrink-0"><path d="M21 12a9 9 0 11-6.219-8.56" /></svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
            </svg>
          )}
          {uploading ? "Uploading…" : "Change Profile Photo"}
        </button>
        <button
          onClick={() => { navigate("/settings"); onClose(); }}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          Settings
        </button>
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
      </div>

      {/* Theme */}
      <div className="px-4 py-3 flex items-center justify-between">
        <span className="text-sm text-muted-foreground">Theme</span>
        <ThemeSelector compact />
      </div>

      {/* Logout */}
      <div className="px-2 py-2">
        <button
          onClick={logout}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-danger hover:bg-destructive/10 transition-colors"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
          </svg>
          Log out
        </button>
      </div>
    </div>
  );
}

export function NavBar() {
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const token = localStorage.getItem("lk_token");
  const { data: profile } = useQuery({
    queryKey: ["me"],
    queryFn: () => getMe().then((r) => r.data),
    enabled: !!token,
    staleTime: 60_000,
  });

  // Close the profile dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) setProfileOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (!token) return null;

  return (
    <nav aria-label="Main" className="border-b border-border bg-background/95 backdrop-blur-sm sticky top-[var(--lk-preview-offset,0px)] z-50">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center gap-2 sm:gap-3">
        {/* Logo — left, always goes to the dashboard once signed in */}
        <Link
          to="/dashboard"
          className="shrink-0 flex min-h-11 items-center text-xl font-bold tracking-wide text-primary"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          Lorekeeper
        </Link>

        {/* Nav menu — a single dropdown at every screen size, instead of a
            flat row of ~10 links that gets cluttered even on desktop */}
        <NavMenu isAdmin={profile?.is_admin === true} />

        {/* Current campaign + role (E0-UX.7) */}
        <CampaignSwitcher />

        {/* Reserved: JobTrayButton slot (E0-Jobs.10) sits here, before the avatar. */}

        {/* Profile — right */}
        <div className="relative shrink-0 ml-auto" ref={profileRef}>
          <button
            onClick={() => setProfileOpen((o) => !o)}
            className="flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-full hover:ring-2 hover:ring-primary/30 transition-all"
            title="Profile"
            aria-label="Profile"
          >
            <Avatar src={profile?.avatar_data} name={profile?.display_name} size={32} />
          </button>
          {profileOpen && (
            <div className="absolute right-0 top-full mt-2 w-64 rounded-xl border border-border bg-background shadow-xl overflow-hidden z-50">
              <ProfileDropdown onClose={() => setProfileOpen(false)} />
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
