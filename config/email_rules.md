Write like a short internal note, not a brochure. Follow Outbound Squad structure: reason, problem, proof, one soft CTA.

Shape
- Plain text. Short paragraphs with a blank line between them. No bullets, no links, no images, no signature block, no street addresses.
- Body under 100 words. Aim for 60 to 90. Four beats, in this order:
  1. Reason / trigger in the first 10 words, about them (a real snippet), not about you.
  2. Problem, phrased as a general pattern with "often", "usually", or "typically". Never state an unverified fact about this prospect. Do not put their company name in the problem sentence.
  3. One matching proof point. Use only the approved facts. You may copy the approved sentence. Do not change numbers. For Polaris, say SKU capacity, never storage capacity.
  4. One soft CTA: an interest question or a light offer such as a one-page summary. Never ask for a meeting, call, calendar time, or "15 minutes".
- More "you" / "your" than "I" / "we" / "our".
- Subject: 1 to 4 words, all lowercase, no numbers, no question mark. It should read like an internal note (for example: "columbus pick walks").
- Day-3 follow-up: its own 1-to-4 word lowercase subject, and a body under 40 words. Add a small useful offer or a light point. Do not write "just checking in".
- Do not name a street address. City and state are fine when they appear in a source.
- One proof point only. Do not list the TAL portfolio.

The enforced banned list and meeting phrases are appended from config/style.yaml. If a word you want is on that list, pick another word.

Style example (fictional prospect; proof facts are the real Garmin case):

Subject: dayton warehouse hiring

Riley - saw Example Goods is expanding its Dayton, Ohio operation and adding warehouse associates this year.

When a site adds people or SKUs, overtime and long pick walks usually show up before throughput does.

At Garmin's Olathe, KS DC, ExactaWCS, conveyor and sortation from Bastian took the work from two 8-hour shifts of 20 people to one 10-hour shift of 7-8.

Would a one-page summary of that shift change be useful on your side?

Follow-up subject: dayton note

Riley - want the one-page note on that Dayton operation for your planning file?

Return JSON only, with keys:
subject, body, followup_subject, followup_body, trigger_source_url, proof_point_id

trigger_source_url must be copied from the research source list. proof_point_id must be the id you were given. body uses newline characters between paragraphs.
