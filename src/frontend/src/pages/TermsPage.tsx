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

// Public page — no auth required, matches HomePage's accessibility. Linked
// from the site-wide Footer and from SubscribePage/RegisterPage wherever a
// "you agree to the Terms" line points here.
export function TermsPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-8">
      <PageHeader title="Terms of Use" description={`Last updated: ${LAST_UPDATED}`} />

      <div className="flex flex-col gap-7">
        <Section title="1. Acceptance of These Terms">
          <p>
            These Terms of Use ("Terms") are an agreement between you and Lorekeeper, operated by Harrison Smith
            doing business as Lorekeeper ("Lorekeeper," "we," "us," or "our"), governing your access to and use of
            the Lorekeeper website, application, and related services (collectively, the "Service") at{" "}
            <a href="https://lorekeeper.quest" className="text-primary hover:underline underline-offset-4">
              lorekeeper.quest
            </a>
            . By creating an account or otherwise using the Service, you agree to be bound by these Terms and by our{" "}
            <Link to="/privacy" className="text-primary hover:underline underline-offset-4">
              Privacy Policy
            </Link>
            , which is incorporated here by reference. If you do not agree, do not use the Service.
          </p>
        </Section>

        <Section title="2. Description of the Service">
          <p>
            Lorekeeper is a journaling application for tabletop and narrative-driven gaming campaigns. It lets you
            record shorthand session notes and turns them into narrative journal entries using AI, either through
            Lorekeeper's own hosted model or a third-party AI provider you connect with your own API key. The
            Service also includes campaign organization tools (timelines, character sheets, quests, session
            planning), session-audio transcription, an AI chat companion, and optional sharing/collaboration
            features.
          </p>
        </Section>

        <Section title="3. Eligibility">
          <p>
            You must be at least 13 years old to use the Service. If you are under 18, you may only use the Service
            with the involvement and consent of a parent or legal guardian. By using the Service, you represent
            that you meet these requirements and that all registration information you provide is accurate.
          </p>
        </Section>

        <Section title="4. Accounts">
          <p>
            You're responsible for maintaining the confidentiality of your login credentials and for all activity
            under your account. Notify us promptly at{" "}
            <a href="mailto:support@lorekeeper.quest" className="text-primary hover:underline underline-offset-4">
              support@lorekeeper.quest
            </a>{" "}
            if you suspect unauthorized use of your account. We may suspend or terminate accounts that violate
            these Terms — see Section 10.
          </p>
        </Section>

        <Section title="5. Subscriptions, Billing, and Promo Codes">
          <p>
            Access to the Service beyond a promo-code grant requires a paid subscription, billed through Stripe on
            a recurring monthly basis until you cancel. Prices and what each plan includes are shown at checkout
            and in your account's billing settings. Subscriptions renew automatically each billing period unless
            canceled before the renewal date; canceling stops future charges but does not refund the current
            period. <strong className="text-foreground">Payments are non-refundable</strong>, including for partial
            months or unused hosted-model quota, except where required by applicable law.
          </p>
          <p>
            A valid promo code grants access without a subscription charge, at whatever plan level the code was
            configured for. Promo-code access can be changed or revoked by an administrator, and doesn't obligate
            you to any future payment — if promo-based access ends, you'll need an active subscription to continue
            using the Service.
          </p>
        </Section>

        <Section title="6. Your Content">
          <p>
            "Your Content" means the journal entries, notes, character sheets, campaign material, uploaded source
            documents, audio recordings, and anything else you submit to the Service. You retain all ownership
            rights in Your Content. By submitting it, you grant Lorekeeper a limited, non-exclusive license to
            store, process, transmit, and display Your Content solely as needed to operate and provide the Service
            to you — including sending relevant parts of it to an AI provider (ours or your own, per Section 7) to
            generate narratives, summaries, or chat responses. This license ends when you delete the content or
            your account, except for copies retained briefly in backups (see our{" "}
            <Link to="/privacy" className="text-primary hover:underline underline-offset-4">
              Privacy Policy
            </Link>
            ).
          </p>
          <p>
            You're responsible for Your Content and for having the rights to submit it. Don't upload material you
            don't have the right to share, or that infringes someone else's rights.
          </p>
        </Section>

        <Section title="7. AI-Generated Content">
          <p>
            Narrative text, summaries, session recaps, tag extraction, and chat responses produced by the Service
            are generated by AI language models and may be inaccurate, incomplete, or inconsistent with your actual
            campaign events. AI output is provided for creative and organizational convenience — review it before
            relying on it, especially anything you plan to treat as an authoritative record. Lorekeeper doesn't
            guarantee the accuracy, quality, or appropriateness of AI-generated content.
          </p>
        </Section>

        <Section title="8. Acceptable Use">
          <p>You agree not to:</p>
          <ul className="list-disc pl-5 flex flex-col gap-1">
            <li>Use the Service for anything unlawful, or to submit content that's illegal, infringing, or abusive;</li>
            <li>Attempt to gain unauthorized access to another user's account, campaign, or data;</li>
            <li>Interfere with or disrupt the Service, including attempting to bypass rate limits, quotas, or account gating;</li>
            <li>Use the Service to generate content that harasses, threatens, or targets a real person;</li>
            <li>Reverse-engineer, scrape, or resell the Service without our written permission.</li>
          </ul>
          <p>Violating this section may result in suspension or termination under Section 10.</p>
        </Section>

        <Section title="9. Sharing & Collaboration Features">
          <p>
            Lorekeeper lets you generate read-only share links and invite other people to collaborate directly on a
            campaign. Anything you share this way is visible to whoever holds the link or accepts the invite —
            think of sharing as public-within-the-link, not private, and only share what you're comfortable with
            others seeing. You're responsible for who you share a campaign with and for managing its collaborators.
          </p>
        </Section>

        <Section title="10. Suspension & Termination">
          <p>
            We may suspend or terminate your access to the Service, with or without notice, if you violate these
            Terms, if required by law, or to protect the Service or other users. You may stop using the Service and
            request account deletion at any time by contacting{" "}
            <a href="mailto:support@lorekeeper.quest" className="text-primary hover:underline underline-offset-4">
              support@lorekeeper.quest
            </a>
            . Sections of these Terms that by their nature should survive termination (ownership, disclaimers,
            limitation of liability) will continue to apply.
          </p>
        </Section>

        <Section title="11. Intellectual Property">
          <p>
            The Service itself — its design, code, branding, and the Lorekeeper name and logo — is owned by
            Lorekeeper and protected by intellectual property law. These Terms don't grant you any rights to it
            beyond what's needed to use the Service as intended.
          </p>
        </Section>

        <Section title="12. AI-Assisted Development">
          <p>
            In the interest of transparency: Lorekeeper — the application itself, including significant parts of
            its backend, frontend, infrastructure, and documentation — was built with the assistance of AI coding
            tools, including Anthropic's Claude and Google's Gemini. This is separate from the AI features the
            Service offers to you (Section 7); it's a disclosure about how the product was engineered. A human
            developer directed, reviewed, and is responsible for the Service, but AI tools were used throughout its
            development process.
          </p>
        </Section>

        <Section title="13. Third-Party Services">
          <p>
            The Service relies on third-party providers to operate, including Stripe (payments), Resend (email
            delivery), Oracle Cloud Infrastructure (hosting), and — only if you choose to connect your own API key
            — OpenAI, Anthropic, or Google as AI providers. Your use of those integrations is also subject to that
            provider's own terms. See our{" "}
            <Link to="/privacy" className="text-primary hover:underline underline-offset-4">
              Privacy Policy
            </Link>{" "}
            for how your data flows to them.
          </p>
        </Section>

        <Section title="14. Disclaimer of Warranties">
          <p>
            The Service is provided "as is" and "as available," without warranties of any kind, express or implied,
            including merchantability, fitness for a particular purpose, and non-infringement. We don't guarantee
            the Service will be uninterrupted, error-free, or that AI-generated content will meet your expectations.
          </p>
        </Section>

        <Section title="15. Limitation of Liability">
          <p>
            To the maximum extent permitted by law, Lorekeeper will not be liable for any indirect, incidental,
            special, consequential, or punitive damages, or any loss of data, revenue, or goodwill, arising from
            your use of the Service. Our total liability for any claim relating to the Service will not exceed the
            amount you paid us in the twelve months before the claim arose.
          </p>
        </Section>

        <Section title="16. Indemnification">
          <p>
            You agree to indemnify and hold Lorekeeper harmless from any claim, loss, or expense (including
            reasonable legal fees) arising from your use of the Service, Your Content, or your violation of these
            Terms.
          </p>
        </Section>

        <Section title="17. Changes to These Terms">
          <p>
            We may update these Terms from time to time. If we make a material change, we'll update the "Last
            updated" date above and, where practical, notify you (e.g., by email or an in-app notice). Continuing
            to use the Service after a change takes effect means you accept the updated Terms.
          </p>
        </Section>

        <Section title="18. Governing Law">
          <p>
            These Terms are governed by the laws of the State of Utah, without regard to its conflict-of-law
            principles, regardless of your location.
          </p>
        </Section>

        <Section title="19. Contact Us">
          <p>
            Questions about these Terms? Reach us at{" "}
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
