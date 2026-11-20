#!/usr/bin/env node
// Checks E0-Access.12's pure Members rules (src/lib/members.ts): the archive
// notice rule (only co_gm → player), the Owner row, the expiry date → ISO
// conversion (end of the local day, with the local offset, in two time
// zones), live links and the login destination. Plus source guards: the
// Sharing page confirms a demotion through pushLayer, the Role picker is the
// SegmentedControl, the Role mutations refetch Members, Roles and Campaigns,
// and login uses loginDestination.
// Dependency-free: node:test + node:assert, members.ts loaded by type stripping.
//
//   node scripts/check-members.mjs

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = join(frontendDir, "src");
const read = (path) => readFileSync(join(srcDir, path), "utf8");

const {
  archiveNotice, archivesChats, expiryDateToIso, isLiveLink, isOwnerRow, loginDestination, todayDateValue,
} = await import("../src/lib/members.ts");

function inZone(tz, fn) {
  const previous = process.env.TZ;
  process.env.TZ = tz;
  try {
    return fn();
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
}

describe("archive notice rule", () => {
  test("only a co_gm → player demotion archives chats", () => {
    assert.equal(archivesChats("co_gm", "player"), true);
    assert.equal(archivesChats("player", "co_gm"), false);
    assert.equal(archivesChats("player", "player"), false);
    assert.equal(archivesChats("co_gm", "co_gm"), false);
    assert.equal(archivesChats("owner", "player"), false);
  });
  test("the notice names the Member and says entries stay, GM-editable only", () => {
    const text = archiveNotice("Mira");
    assert.match(text, /Mira/);
    assert.ok(text.includes("Their NPC Conversations and chat history in this Campaign will be archived."), text);
    assert.match(text, /only GMs can edit them/);
  });
});

describe("owner row", () => {
  test("member_id null or role owner is the Owner row", () => {
    assert.equal(isOwnerRow({ member_id: null, role: "owner" }), true);
    assert.equal(isOwnerRow({ member_id: null, role: "player" }), true);
    assert.equal(isOwnerRow({ member_id: "m1", role: "owner" }), true);
    assert.equal(isOwnerRow({ member_id: "m1", role: "co_gm" }), false);
    assert.equal(isOwnerRow({ member_id: "m1", role: "player" }), false);
  });
});

describe("expiry date → ISO", () => {
  test("empty is no expiry; junk and impossible dates are undefined", () => {
    assert.equal(expiryDateToIso(""), null);
    for (const bad of ["2026-13-01", "2026-02-30", "tomorrow", "2026-1-1", "2026-12-01T00:00"]) {
      assert.equal(expiryDateToIso(bad), undefined, bad);
    }
  });
  test("end of the local day with the local offset", () => {
    inZone("America/New_York", () => {
      assert.equal(expiryDateToIso("2026-12-01"), "2026-12-01T23:59:59.999-05:00");
      assert.equal(expiryDateToIso("2026-07-04"), "2026-07-04T23:59:59.999-04:00");
    });
    inZone("Asia/Kolkata", () => {
      assert.equal(expiryDateToIso("2026-12-01"), "2026-12-01T23:59:59.999+05:30");
    });
    inZone("UTC", () => {
      assert.equal(expiryDateToIso("2026-12-01"), "2026-12-01T23:59:59.999+00:00");
    });
  });
  test("the ISO string is that instant", () => {
    inZone("America/New_York", () => {
      const iso = expiryDateToIso("2026-12-01");
      assert.equal(new Date(iso).getTime(), new Date(2026, 11, 1, 23, 59, 59, 999).getTime());
    });
  });
  test("today as a date input value", () => {
    assert.equal(todayDateValue(new Date(2026, 0, 5, 12)), "2026-01-05");
  });
});

describe("live links", () => {
  const now = new Date("2026-11-20T12:00:00Z");
  test("revoked or past expiry is not live", () => {
    assert.equal(isLiveLink({ revoked: false, expires_at: null }, now), true);
    assert.equal(isLiveLink({ revoked: true, expires_at: null }, now), false);
    assert.equal(isLiveLink({ revoked: false, expires_at: "2026-11-21T00:00:00Z" }, now), true);
    assert.equal(isLiveLink({ revoked: false, expires_at: "2026-11-20T12:00:00Z" }, now), false);
  });
});

describe("login destination", () => {
  test("paid, or unpaid but in a Campaign, → dashboard; otherwise subscribe", () => {
    assert.equal(loginDestination(true, 0), "/dashboard");
    assert.equal(loginDestination(true, 3), "/dashboard");
    assert.equal(loginDestination(false, 1), "/dashboard");
    assert.equal(loginDestination(false, 0), "/subscribe");
  });
});

describe("source guards", () => {
  const page = read("pages/SharingPage.tsx");
  const hooks = read("hooks/useSharing.ts");
  const auth = read("hooks/useAuth.ts");
  test("the Sharing page confirms through pushLayer and uses the primitives", () => {
    for (const needle of ["pushLayer(", "<SegmentedControl", "<RoleBadge", "archiveNotice(", "archivesChats(",
      "<Skeleton", "<EmptyState", "<InlineError", "expiryDateToIso("]) {
      assert.ok(page.includes(needle), `SharingPage.tsx uses ${needle}`);
    }
    assert.ok(!page.includes("confirm("), "no window.confirm: confirmations are inline and Esc-cancellable");
    assert.ok(!page.includes("m.email"), "the Members list carries no email");
  });
  test("Role and membership mutations refetch Members, Roles and Campaigns", () => {
    for (const needle of ["campaignMembersKey(", "campaignRoleKey(", '["campaigns"]', "changeMemberRole("]) {
      assert.ok(hooks.includes(needle), `useSharing.ts uses ${needle}`);
    }
  });
  test("login goes through loginDestination", () => {
    assert.ok(auth.includes("loginDestination("), "useAuth.ts uses loginDestination");
  });
});
