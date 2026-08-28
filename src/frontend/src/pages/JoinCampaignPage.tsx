import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as api from "../services/api";
import type { PublicCampaign } from "../types";

export function JoinCampaignPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const isLoggedIn = !!localStorage.getItem("lk_token");
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: campaign, isLoading, isError } = useQuery<PublicCampaign>({
    queryKey: ["sharedCampaign", token],
    queryFn: async () => (await api.getSharedCampaign(token!)).data,
    enabled: !!token,
    retry: false,
  });

  useEffect(() => {
    if (campaign?.share_kind === "read_only") {
      navigate(`/shared/${token}`, { replace: true });
    }
  }, [campaign, token, navigate]);

  const handleJoin = async () => {
    if (!token) return;
    setJoining(true);
    setError(null);
    try {
      const { data } = await api.joinCampaign(token);
      navigate("/", { replace: true, state: { joinedCampaignId: data.campaign_id } });
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not join this campaign. The link may be invalid or revoked.");
    } finally {
      setJoining(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-card p-6 flex flex-col gap-4 text-center">
        <p className="text-4xl">🤝</p>

        {isLoading && <div className="h-6 w-48 mx-auto bg-muted rounded animate-pulse" />}
        {isError && <p className="text-sm text-destructive">This invite link is invalid or has been revoked.</p>}

        {campaign && campaign.share_kind === "collaborate" && (
          <>
            <div>
              <h1 className="text-lg font-semibold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
                You've been invited to join
              </h1>
              <p className="text-xl font-bold text-primary mt-1">{campaign.name}</p>
              <p className="text-xs text-muted-foreground capitalize mt-1">{campaign.genre} campaign</p>
            </div>

            {isLoggedIn ? (
              <>
                <p className="text-sm text-muted-foreground">
                  Joining lets you write journal entries, characters, and quests into this campaign
                  alongside the rest of the party.
                </p>
                <button
                  onClick={handleJoin}
                  disabled={joining}
                  className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  {joining ? "Joining…" : "Join Campaign"}
                </button>
                {error && <p className="text-sm text-destructive">{error}</p>}
              </>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">
                  Log in or create an account, then come back to this link to finish joining.
                </p>
                <div className="flex gap-2">
                  <Link to="/login" className="flex-1 rounded-md border border-input px-4 py-2.5 text-sm font-medium text-foreground hover:bg-muted/60 transition-colors">
                    Log In
                  </Link>
                  <Link to="/register" className="flex-1 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-90 transition-opacity">
                    Create Account
                  </Link>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
