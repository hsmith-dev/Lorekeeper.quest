import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";

const LAST_UPDATED = "August 16, 2026";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5">
      <h2 className="text-lg font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
        {title}
      </h2>
      <div className="flex flex-col gap-2.5 text-sm text-muted-foreground leading-relaxed">{children}</div>
    </section>
  );
}

// Public page — no auth required. See TermsPage.tsx for the sibling
// document; both are linked from the site-wide Footer.
export function PrivacyPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-8">
      <PageHeader title="Privacy Policy" description={`Last updated: ${LAST_UPDATED}`} />

      <div className="flex flex-col gap-7">
        <Section title="1. Overview">
          <p>
            This Privacy Policy explains what information Lorekeeper ("we," "us," "our") collects when you use{" "}
            <a href="https://lorekeeper.quest" className="text-primary hover:underline underline-offset-4">
              lorekeeper.quest
            </a>{" "}
            (the "Service"), how we use it, and the choices you have. It should be read alongside our{" "}
            <Link to="/terms" className="text-primary hover:underline underline-offset-4">
              Terms of Use
            </Link>
            . If you have questions, contact us at{" "}
            <a href="mailto:support@lorekeeper.quest" className="text-primary hover:underline underline-offset-4">
              support@lorekeeper.quest
            </a>
            .
          </p>
        </Section>

        <Section title="2. Information We Collect">
          <p>
            <strong className="text-foreground">Account information:</strong> the email address, password (stored
            as a salted hash — we never see or store your plaintext password), and display name you register with,
            plus an optional avatar image you upload.
          </p>
          <p>
            <strong className="text-foreground">Content you provide:</strong> journal entries and shorthand notes,
            campaign and character data, quests, session plans, custom tags and glossary terms, source documents
            you upload for AI grounding, and session audio you record for transcription.
          </p>
          <p>
            <strong className="text-foreground">Payment information:</strong> if you subscribe, Stripe processes
            your payment and collects your billing details directly — we never see or store your full card number.
            We keep a record of your subscription status, plan, and billing history as reported to us by Stripe.
          </p>
          <p>
            <strong className="text-foreground">Usage and log data:</strong> IP address, timestamps, and request
            metadata, collected automatically for security purposes such as rate-limiting login attempts and
            diagnosing errors.
          </p>
        </Section>

        <Section title="3. How We Use Your Information">
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>To provide the Service — generate narratives, summaries, tags, and chat responses from your content;</li>
            <li>To operate your account — authentication, billing, promo-code redemption, and support requests;</li>
            <li>To secure the Service — detect and block abusive login attempts, enforce rate limits, and investigate suspected fraud or abuse;</li>
            <li>To communicate with you — transactional email such as welcome messages, password resets, and billing notices;</li>
            <li>To maintain the Service — backups, debugging, and improving reliability.</li>
          </ul>
          <p>We do not sell your personal information, and we do not use your journal content to serve ads — the Service doesn't have any.</p>
        </Section>

        <Section title="4. AI Processing">
          <p>
            <strong className="text-foreground">Lorekeeper's hosted model:</strong> if you use Lorekeeper's own AI
            (the default, metered hosted-model option), your notes and relevant campaign context are sent to a
            language model we run ourselves on our own cloud infrastructure — it does not leave infrastructure we
            control.
          </p>
          <p>
            <strong className="text-foreground">Your own API key:</strong> if you connect your own OpenAI,
            Anthropic, or Google Gemini API key (or another OpenAI-compatible endpoint) in Settings, the relevant
            journal content is sent from our servers to that provider, using your key, to generate the response.
            That transmission and any resulting processing is governed by that provider's own privacy policy and
            terms, not this one — we encourage you to review them before connecting a key.
          </p>
          <p>
            <strong className="text-foreground">Voice transcription:</strong> session-recording audio is
            transcribed locally on our own server using an offline speech-to-text model — it is never sent to a
            third party. The audio file itself is deleted immediately after transcription; only the resulting text
            is saved to your journal entry.
          </p>
        </Section>

        <Section title="5. How We Share Information">
          <p>We share information only as needed to run the Service:</p>
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li><strong className="text-foreground">Stripe</strong> — payment processing and subscription management;</li>
            <li><strong className="text-foreground">Resend</strong> — delivery of transactional email (welcome, password reset, billing notices);</li>
            <li><strong className="text-foreground">Oracle Cloud Infrastructure</strong> — hosting for the application, database, and self-hosted AI model;</li>
            <li><strong className="text-foreground">Your chosen AI provider</strong> (OpenAI, Anthropic, or Google) — only if you connect your own API key, as described in Section 4.</li>
          </ul>
          <p>We may also disclose information if required by law, or to protect the rights, safety, or property of Lorekeeper or our users.</p>
        </Section>

        <Section title="6. Data Retention & Backups">
          <p>
            We retain your account and content data for as long as your account is active. We take nightly
            database backups, retained for 14 days on our hosting infrastructure, so that content can be recovered
            after an incident. If you delete your account (Section 8), your data is removed from the live
            database, but a copy may persist in backups for up to 14 days until they naturally roll off.
          </p>
        </Section>

        <Section title="7. Data Security">
          <p>
            Traffic to and from the Service is encrypted with HTTPS/TLS. Passwords are hashed with bcrypt and never
            stored in plaintext. We apply per-account and per-IP protections against repeated failed login attempts,
            and access to administrative functions is restricted to designated admin accounts. No system is
            perfectly secure, and we can't guarantee absolute security, but we take reasonable, industry-standard
            measures to protect your information.
          </p>
        </Section>

        <Section title="8. Your Choices & Rights">
          <p>
            You can update your display name and avatar directly in Settings. To access, correct, export, or delete
            your account and associated data, contact us at{" "}
            <a href="mailto:support@lorekeeper.quest" className="text-primary hover:underline underline-offset-4">
              support@lorekeeper.quest
            </a>
            — account deletion isn't currently self-service, so we handle these requests directly and will confirm
            once it's done. If you're subscribed through Stripe, canceling your subscription (Settings → Billing)
            stops future charges independently of any deletion request.
          </p>
        </Section>

        <Section title="9. Sharing & Collaboration Features">
          <p>
            If you generate a read-only share link or invite someone to collaborate on a campaign, the content in
            that campaign becomes visible to whoever holds the link or accepts the invite. This is a feature you
            opt into per-campaign — content isn't shared this way unless you create a link or send an invite
            yourself. See our{" "}
            <Link to="/terms" className="text-primary hover:underline underline-offset-4">
              Terms of Use
            </Link>{" "}
            for more on how sharing works.
          </p>
        </Section>

        <Section title="10. Cookies & Tracking">
          <p>
            The Service does not use cookies or third-party tracking/analytics scripts. Your login session is kept
            in your browser's local storage, not a cookie, and never leaves your device except when sent to us to
            authenticate a request.
          </p>
        </Section>

        <Section title="11. Children's Privacy">
          <p>
            The Service is not directed at children under 13, and we don't knowingly collect information from
            anyone under 13. If you believe a child under 13 has created an account, contact us at{" "}
            <a href="mailto:support@lorekeeper.quest" className="text-primary hover:underline underline-offset-4">
              support@lorekeeper.quest
            </a>{" "}
            and we'll remove it.
          </p>
        </Section>

        <Section title="12. International Users">
          <p>
            The Service is hosted on cloud infrastructure that may be located outside your country of residence.
            By using the Service, you understand that your information may be transferred to and processed in a
            country with different data protection laws than your own.
          </p>
        </Section>

        <Section title="13. Changes to This Policy">
          <p>
            We may update this Privacy Policy from time to time. If we make a material change, we'll update the
            "Last updated" date above and, where practical, notify you. Continuing to use the Service after a
            change takes effect means you accept the updated policy.
          </p>
        </Section>

        <Section title="14. Contact Us">
          <p>
            Questions about this policy or your data? Reach us at{" "}
            <a href="mailto:support@lorekeeper.quest" className="text-primary hover:underline underline-offset-4">
              support@lorekeeper.quest
            </a>
            .
          </p>
        </Section>
      </div>
    </div>
  );
}
