import { useState, useRef, useEffect } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { ThemeSelector } from "./ThemeSelector";
import { uploadAvatar, getMe } from "../services/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";

// Grouped rather than one flat list — 14 ungrouped links (before Admin is
// even added) is hard to scan no matter how the dropdown itself is styled.
// Every existing route stays exactly where it was; this only adds section
// labels and a visual grouping on top.
const NAV_GROUPS: { label: string; links: { to: string; label: string }[] }[] = [
  {
    label: "Chronicle",
    links: [
      { to: "/dashboard", label: "Journal" },
      { to: "/history", label: "History" },
      { to: "/timeline", label: "Timeline" },
      { to: "/record", label: "Record Session" },
      { to: "/analytics", label: "Analytics" },
    ],
  },
  {
    label: "Campaign",
    links: [
      { to: "/characters", label: "Characters" },
      { to: "/character-sheets", label: "Character Sheets" },
      { to: "/quests", label: "Quests" },
      { to: "/session-plans", label: "Session Plans" },
      { to: "/sources", label: "Sources" },
      { to: "/shorthand", label: "Shorthand" },
    ],
  },
  {
    label: "Collaborate",
    links: [
      { to: "/sharing", label: "Sharing" },
      { to: "/feedback", label: "Feedback" },
    ],
  },
];

// Flattened view — still used for "what's the current page called" lookups
// and for building the admin-augmented list without duplicating every group.
const NAV_LINKS = NAV_GROUPS.flatMap((g) => g.links);

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
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-destructive hover:bg-destructive/10 transition-colors"
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
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const token = localStorage.getItem("lk_token");
  const { data: profile } = useQuery({
    queryKey: ["me"],
    queryFn: () => getMe().then((r) => r.data),
    enabled: !!token,
    staleTime: 60_000,
  });

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) setProfileOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Close the nav menu on navigation
  useEffect(() => setMenuOpen(false), [location.pathname]);

  if (!token) return null;

  const isActive = (to: string) => location.pathname.startsWith(to);
  // Admin only shows for the configured admin (see
  // app/api/deps.py::require_admin) — the route itself also self-guards, so
  // this is purely about not cluttering the menu for everyone else. Kept as
  // its own trailing group rather than folded into "Collaborate" — it's a
  // fundamentally different kind of link (operating the platform, not using
  // it) and admins are rare enough that a dedicated, clearly-separated
  // section is worth the one extra label.
  const groups = profile?.is_admin
    ? [...NAV_GROUPS, { label: "Admin", links: [{ to: "/admin", label: "Admin" }] }]
    : NAV_GROUPS;
  const current = NAV_LINKS.find((l) => isActive(l.to)) ?? (isActive("/admin") ? { to: "/admin", label: "Admin" } : undefined);

  return (
    <nav className="border-b border-border bg-background/95 backdrop-blur-sm sticky top-0 z-50">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center gap-3">
        {/* Logo — left, always goes to the dashboard once signed in */}
        <Link
          to="/dashboard"
          className="shrink-0 text-xl font-bold tracking-wide text-primary"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          Lorekeeper
        </Link>

        {/* Nav menu — a single dropdown at every screen size, instead of a
            flat row of ~10 links that gets cluttered even on desktop */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-foreground hover:bg-muted/60 transition-colors border border-border"
          >
            <svg width="15" height="15" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" clipRule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" />
            </svg>
            <span className="max-w-[10rem] truncate">{current?.label ?? "Menu"}</span>
            <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor" className={`transition-transform shrink-0 ${menuOpen ? "rotate-180" : ""}`}>
              <path fillRule="evenodd" clipRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" />
            </svg>
          </button>
          {menuOpen && (
            <div className="absolute left-0 top-full mt-2 w-60 rounded-xl border border-border bg-background shadow-xl overflow-hidden z-50 py-1.5 max-h-[75vh] overflow-y-auto">
              {groups.map((group, i) => (
                <div key={group.label} className={i > 0 ? "mt-1.5 pt-1.5 border-t border-border" : ""}>
                  <p className="px-4 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
                    {group.label}
                  </p>
                  {group.links.map(({ to, label }) => (
                    <Link
                      key={to}
                      to={to}
                      className={`block px-4 py-2 text-sm transition-colors ${
                        isActive(to)
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

        {/* Profile — right */}
        <div className="relative shrink-0 ml-auto" ref={profileRef}>
          <button
            onClick={() => setProfileOpen((o) => !o)}
            className="flex items-center gap-2 rounded-full p-0.5 hover:ring-2 hover:ring-primary/30 transition-all"
            title="Profile"
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
