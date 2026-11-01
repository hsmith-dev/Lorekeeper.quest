# Upgrading Lorekeeper

Notes for self-hosters on what an upgrade changes in your data. Every
upgrade runs `alembic upgrade head` when the web container starts; there is
nothing to run by hand.

## NPCs and Quests become Entities (F3-world, E0-WorldCore.2)

Your NPCs and Quests are now Entities. They start GM-only. Your Players, who were Members before this release, see none of them until you publish them from World.

What the upgrade does:

- Every NPC becomes a Character (kind PC, NPC or Creature, from its old
  role), and every NPC with the role Faction becomes a Faction. Statuses map
  to the new vocabulary: alive stays alive, dead becomes deceased, unknown
  stays unknown. For a Faction, alive becomes active, dead becomes
  disbanded, and unknown stays unknown.
- Every Quest becomes a Quest Entity with its status unchanged. A completed
  Quest records when it was completed (its last update).
- Names, descriptions, creation and update times carry over. Your private
  notes become the Entity's GM notes, which Players never see.
- Each Entity's history starts with one entry, "Came over from your NPC
  list" (or Quest list).
- Every existing Campaign gets the default relationship types (Ally of,
  Enemy of, Member of, Located in, Owns, Related to).

Your old NPC and Quest rows are kept as they were. The copy is safe to run
again: it never duplicates an Entity. A value it does not recognise takes
the default status (or kind NPC) and is written to the upgrade log instead
of stopping the upgrade.
