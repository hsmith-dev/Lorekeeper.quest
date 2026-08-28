import { useState } from "react";
import { useCampaigns } from "../hooks/useCampaigns";
import {
  useCharacterTemplates, useCreateCharacterTemplate, useUpdateCharacterTemplate, useDeleteCharacterTemplate,
  useCharacterSheets, useCreateCharacterSheet, useUpdateCharacterSheet, useDeleteCharacterSheet,
} from "../hooks/useCharacterSheets";
import { PageHeader } from "../components/PageHeader";
import type { Campaign, CharacterSheetTemplate, CharacterSheet, CharacterTemplateField, CharacterFieldType, CharacterFieldValue } from "../types";

const FIELD_TYPE_LABEL: Record<CharacterFieldType, string> = {
  text: "Text", number: "Number", long_text: "Long Text", list: "List",
};

function slugify(label: string, taken: Set<string>): string {
  const base = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "field";
  let key = base;
  let n = 2;
  while (taken.has(key)) key = `${base}_${n++}`;
  return key;
}

// ─── Template field builder (shared by create + edit) ───────────────────────

function FieldBuilder({ fields, onChange }: { fields: CharacterTemplateField[]; onChange: (f: CharacterTemplateField[]) => void }) {
  const addField = () => {
    const taken = new Set(fields.map((f) => f.key));
    onChange([...fields, { key: slugify("New Field", taken), label: "New Field", type: "text" }]);
  };
  const updateField = (i: number, patch: Partial<CharacterTemplateField>) => {
    onChange(fields.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  };
  const removeField = (i: number) => onChange(fields.filter((_, idx) => idx !== i));

  return (
    <div className="flex flex-col gap-2">
      {fields.length === 0 && (
        <p className="text-xs text-muted-foreground italic">No fields yet — add one below.</p>
      )}
      {fields.map((f, i) => (
        // Column below sm, row from sm up — three controls (text input, type
        // select, delete) in one row got uncomfortably cramped on a phone
        // width once the select's label text (e.g. "Long Text") had to share
        // space with everything else.
        <div key={i} className="flex flex-col sm:flex-row sm:items-center gap-2">
          <input
            type="text"
            value={f.label}
            onChange={(e) => updateField(i, { label: e.target.value })}
            placeholder="Field label"
            className="flex-1 min-w-0 rounded-md border border-input bg-background px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <div className="flex items-center gap-2">
            <select
              value={f.type}
              onChange={(e) => updateField(i, { type: e.target.value as CharacterFieldType })}
              className="flex-1 sm:flex-initial rounded-md border border-input bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            >
              {(Object.keys(FIELD_TYPE_LABEL) as CharacterFieldType[]).map((t) => (
                <option key={t} value={t}>{FIELD_TYPE_LABEL[t]}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => removeField(i)}
              title="Remove field"
              className="shrink-0 p-1.5 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" clipRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" /></svg>
            </button>
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={addField}
        className="self-start text-xs text-primary hover:underline underline-offset-2"
      >
        + Add field
      </button>
    </div>
  );
}

// ─── Template manager ────────────────────────────────────────────────────────

function TemplateEditor({
  campaign, template, onDone,
}: { campaign: Campaign; template: CharacterSheetTemplate | null; onDone: () => void }) {
  const [name, setName] = useState(template?.name ?? "");
  const [fields, setFields] = useState<CharacterTemplateField[]>(template?.fields ?? []);
  const create = useCreateCharacterTemplate(campaign.id);
  const update = useUpdateCharacterTemplate(campaign.id);
  const pending = create.isPending || update.isPending;

  const handleSave = () => {
    if (!name.trim() || fields.length === 0) return;
    if (template) {
      update.mutate({ id: template.id, data: { name: name.trim(), fields } }, { onSuccess: onDone });
    } else {
      create.mutate({ name: name.trim(), fields }, { onSuccess: onDone });
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-3">
      <input
        type="text"
        placeholder="Template name — e.g. D&D 5e Character"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring"
      />
      <FieldBuilder fields={fields} onChange={setFields} />
      <div className="flex items-center justify-end gap-2 pt-1">
        <button onClick={onDone} className="text-xs px-3 py-1.5 rounded-md border border-input text-muted-foreground hover:text-foreground transition-colors">
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={pending || !name.trim() || fields.length === 0}
          className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {pending ? "Saving…" : template ? "Save Template" : "Create Template"}
        </button>
      </div>
    </div>
  );
}

function TemplateManager({ campaign }: { campaign: Campaign }) {
  const { data: templates, isLoading } = useCharacterTemplates(campaign.id);
  const deleteTemplate = useDeleteCharacterTemplate(campaign.id);
  const [editing, setEditing] = useState<CharacterSheetTemplate | null | "new">(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  if (editing) {
    return (
      <TemplateEditor
        campaign={campaign}
        template={editing === "new" ? null : editing}
        onDone={() => setEditing(null)}
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {isLoading && <p className="text-xs text-muted-foreground">Loading templates…</p>}
      {!isLoading && (templates ?? []).length === 0 && (
        <p className="text-xs text-muted-foreground italic">
          No templates yet — create one to define what a character sheet looks like for this campaign's system.
        </p>
      )}
      {(templates ?? []).map((t) => (
        <div key={t.id} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-3 py-2.5">
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{t.name}</p>
            <p className="text-xs text-muted-foreground">
              {t.fields.length} field{t.fields.length === 1 ? "" : "s"} · {t.character_count} character{t.character_count === 1 ? "" : "s"}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={() => setEditing(t)} className="text-xs px-2.5 py-1 rounded-md border border-input text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors">
              Edit
            </button>
            {confirmDelete === t.id ? (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">
                  {t.character_count > 0 ? `Deletes ${t.character_count} character${t.character_count === 1 ? "" : "s"} too?` : "Sure?"}
                </span>
                <button
                  onClick={() => deleteTemplate.mutate(t.id, { onSuccess: () => setConfirmDelete(null) })}
                  className="text-xs px-2 py-1 rounded-md bg-destructive text-destructive-foreground font-medium hover:opacity-90"
                >
                  Confirm
                </button>
                <button onClick={() => setConfirmDelete(null)} className="text-xs px-2 py-1 rounded-md border border-input text-muted-foreground">
                  Cancel
                </button>
              </div>
            ) : (
              <button onClick={() => setConfirmDelete(t.id)} className="text-xs px-2.5 py-1 rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors">
                Delete
              </button>
            )}
          </div>
        </div>
      ))}
      <button onClick={() => setEditing("new")} className="self-start text-xs text-primary hover:underline underline-offset-2 mt-1">
        + New Template
      </button>
    </div>
  );
}

// ─── Field value input (dynamic, per type) ──────────────────────────────────

function FieldInput({
  field, value, onChange,
}: { field: CharacterTemplateField; value: CharacterFieldValue; onChange: (v: CharacterFieldValue) => void }) {
  if (field.type === "long_text") {
    return (
      <textarea
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
        rows={4}
        className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
      />
    );
  }
  if (field.type === "number") {
    return (
      <input
        type="number"
        value={value === null || value === undefined ? "" : (value as number)}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
      />
    );
  }
  if (field.type === "list") {
    const list = Array.isArray(value) ? value : [];
    return (
      <input
        type="text"
        value={list.join(", ")}
        onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
        placeholder="Comma-separated — sword, torch, rope…"
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
      />
    );
  }
  return (
    <input
      type="text"
      value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
    />
  );
}

// ─── Character editor (create or edit) ──────────────────────────────────────

function CharacterEditor({
  campaign, templates, character, defaultTemplateId, onDone, onCancel,
}: {
  campaign: Campaign; templates: CharacterSheetTemplate[]; character: CharacterSheet | null;
  defaultTemplateId?: string; onDone: () => void; onCancel: () => void;
}) {
  const [templateId, setTemplateId] = useState(character?.template_id ?? defaultTemplateId ?? templates[0]?.id ?? "");
  const [name, setName] = useState(character?.name ?? "");
  const [data, setData] = useState<Record<string, CharacterFieldValue>>(character?.data ?? {});
  const create = useCreateCharacterSheet(campaign.id);
  const update = useUpdateCharacterSheet(campaign.id);
  const template = templates.find((t) => t.id === templateId);
  const pending = create.isPending || update.isPending;

  const handleSave = () => {
    if (!name.trim() || !templateId) return;
    if (character) {
      update.mutate({ id: character.id, data: { name: name.trim(), data } }, { onSuccess: onDone });
    } else {
      create.mutate({ template_id: templateId, name: name.trim(), data }, { onSuccess: onDone });
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-3">
      <input
        type="text"
        placeholder="Character name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        autoFocus
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring"
      />
      {!character && (
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block">Template</label>
          <select
            value={templateId}
            onChange={(e) => { setTemplateId(e.target.value); setData({}); }}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          >
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
      )}
      {template && template.fields.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {template.fields.map((f) => (
            <div key={f.key} className={f.type === "long_text" ? "sm:col-span-2" : ""}>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">{f.label}</label>
              <FieldInput
                field={f}
                value={data[f.key] ?? null}
                onChange={(v) => setData((d) => ({ ...d, [f.key]: v }))}
              />
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center justify-end gap-2 pt-1">
        <button onClick={onCancel} className="text-xs px-3 py-1.5 rounded-md border border-input text-muted-foreground hover:text-foreground transition-colors">
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={pending || !name.trim() || !templateId}
          className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {pending ? "Saving…" : character ? "Save Character" : "Create Character"}
        </button>
      </div>
    </div>
  );
}

function CharacterCard({
  character, template, onEdit, onDelete,
}: { character: CharacterSheet; template: CharacterSheetTemplate | undefined; onEdit: () => void; onDelete: () => void }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const preview = (template?.fields ?? []).slice(0, 3);

  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-card-foreground truncate">{character.name}</p>
          <p className="text-xs text-muted-foreground">{template?.name ?? "Unknown template"}</p>
        </div>
      </div>
      {preview.length > 0 && (
        <dl className="flex flex-col gap-1">
          {preview.map((f) => {
            const v = character.data[f.key];
            const display = Array.isArray(v) ? v.join(", ") : v ?? "—";
            return (
              <div key={f.key} className="flex items-baseline gap-1.5 text-xs">
                <dt className="text-muted-foreground shrink-0">{f.label}:</dt>
                <dd className="text-foreground truncate">{String(display) || "—"}</dd>
              </div>
            );
          })}
        </dl>
      )}
      <div className="flex items-center gap-2 pt-1">
        <button onClick={onEdit} className="text-xs px-2.5 py-1 rounded-md border border-input text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors">
          Edit
        </button>
        {confirmDelete ? (
          <div className="flex items-center gap-1.5">
            <button onClick={onDelete} className="text-xs px-2 py-1 rounded-md bg-destructive text-destructive-foreground font-medium hover:opacity-90">
              Confirm
            </button>
            <button onClick={() => setConfirmDelete(false)} className="text-xs px-2 py-1 rounded-md border border-input text-muted-foreground">
              Cancel
            </button>
          </div>
        ) : (
          <button onClick={() => setConfirmDelete(true)} className="text-xs px-2.5 py-1 rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors">
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Per-campaign content ────────────────────────────────────────────────────

function CampaignCharacterSheets({ campaign }: { campaign: Campaign }) {
  const { data: templates, isLoading: templatesLoading } = useCharacterTemplates(campaign.id);
  const { data: sheets, isLoading: sheetsLoading } = useCharacterSheets(campaign.id);
  const deleteSheet = useDeleteCharacterSheet(campaign.id);
  const [showTemplates, setShowTemplates] = useState(false);
  const [editingSheet, setEditingSheet] = useState<CharacterSheet | null>(null);
  const [creatingSheet, setCreatingSheet] = useState(false);

  const templateById = (id: string) => (templates ?? []).find((t) => t.id === id);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <button
          onClick={() => setShowTemplates((v) => !v)}
          className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className={`transition-transform ${showTemplates ? "rotate-90" : ""}`}>
            <polyline points="9 18 15 12 9 6" />
          </svg>
          Templates ({(templates ?? []).length})
        </button>
        {showTemplates && (
          <div className="mt-3">
            <TemplateManager campaign={campaign} />
          </div>
        )}
      </div>

      <div className="border-t border-border pt-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Characters
          </h2>
          {!creatingSheet && (templates ?? []).length > 0 && (
            <button
              onClick={() => setCreatingSheet(true)}
              className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity"
            >
              + New Character
            </button>
          )}
        </div>

        {(templatesLoading || sheetsLoading) && <p className="text-xs text-muted-foreground">Loading…</p>}

        {!templatesLoading && (templates ?? []).length === 0 && (
          <div className="text-center py-12 text-muted-foreground border border-dashed border-border rounded-xl">
            <p className="text-3xl mb-2">🧙</p>
            <p className="text-sm font-medium text-foreground mb-1">No templates yet</p>
            <p className="text-xs">Open Templates above and create one before adding characters.</p>
          </div>
        )}

        {creatingSheet && (templates ?? []).length > 0 && (
          <div className="mb-3">
            <CharacterEditor
              campaign={campaign}
              templates={templates ?? []}
              character={null}
              onDone={() => setCreatingSheet(false)}
              onCancel={() => setCreatingSheet(false)}
            />
          </div>
        )}

        {!sheetsLoading && (templates ?? []).length > 0 && (sheets ?? []).length === 0 && !creatingSheet && (
          <p className="text-sm text-muted-foreground text-center py-8">No characters yet — create one above.</p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {(sheets ?? []).map((c) =>
            editingSheet?.id === c.id ? (
              <div key={c.id} className="sm:col-span-2">
                <CharacterEditor
                  campaign={campaign}
                  templates={templates ?? []}
                  character={c}
                  onDone={() => setEditingSheet(null)}
                  onCancel={() => setEditingSheet(null)}
                />
              </div>
            ) : (
              <CharacterCard
                key={c.id}
                character={c}
                template={templateById(c.template_id)}
                onEdit={() => setEditingSheet(c)}
                onDelete={() => deleteSheet.mutate(c.id)}
              />
            )
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function CharacterSheetsPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        dataTour="character-sheets-heading"
        title="Character Sheets"
        description="Build a custom sheet template for your game system, then fill one in per character — separate from your journal."
      />

      {campaigns && campaigns.length > 0 && (
        <div className="flex gap-1.5 flex-wrap border-b border-border pb-3">
          {campaigns.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelected(c)}
              className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                selected?.id === c.id ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
              }`}
            >
              {c.name}
              {!c.is_owner && <span className="ml-1 text-[10px] text-primary/70">shared</span>}
            </button>
          ))}
        </div>
      )}

      {!selected && (
        <div className="text-center py-16 text-muted-foreground">
          <p className="text-4xl mb-3">🛡️</p>
          <p className="text-sm">Select a campaign above to view its character sheets.</p>
        </div>
      )}

      {selected && <CampaignCharacterSheets campaign={selected} />}
    </div>
  );
}
