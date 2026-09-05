import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getModelStatus, getMe } from "../services/api";

/** Fresh-deployment guardrail: when the account's effective backend is the
 *  platform's local model server and no model is installed (or the server is
 *  down), say so up front — with the one-click fix for admins — instead of
 *  letting the first generation fail with a generic error. Renders nothing
 *  once everything is ready, and never blocks the page on its own loading. */
export function ModelReadyBanner() {
  const { data: status } = useQuery({
    queryKey: ["model-status"],
    queryFn: () => getModelStatus().then((r) => r.data),
    staleTime: 60_000,
    retry: false,
  });
  const { data: profile } = useQuery({
    queryKey: ["me"],
    queryFn: () => getMe().then((r) => r.data),
    staleTime: 60_000,
  });

  if (!status || !status.uses_local_default) return null;
  if (status.server_reachable && status.model_installed) return null;

  const isAdmin = profile?.is_admin ?? false;
  const serverDown = !status.server_reachable;

  return (
    <div className="mb-5 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
      <p className="font-semibold text-foreground mb-1">
        {serverDown ? "⚠ The AI model server isn't reachable" : "⚠ No AI model is installed yet"}
      </p>
      <p className="text-muted-foreground">
        {serverDown ? (
          <>
            Generation features (journal drafts, chat, session plans) won't work until it's back.
            {isAdmin
              ? " Check that the ollama container is running (docker compose ps), then see Admin → System."
              : " Ask your instance admin to take a look."}
          </>
        ) : (
          <>
            This deployment serves its AI locally, but the model{" "}
            <span className="font-mono">{status.model_name}</span> hasn't been downloaded yet.
            {isAdmin ? (
              <>
                {" "}Install it in one click —{" "}
                <Link to="/admin?tab=system" className="underline font-medium text-foreground">
                  open the Model Library
                </Link>
                {" "}(~4.4 GB, straight from Hugging Face).
              </>
            ) : (
              " Ask your instance admin to install it from Admin → System, or configure your own AI provider under Settings."
            )}
          </>
        )}
      </p>
    </div>
  );
}
