import { redirect } from "next/navigation";

// The Strategy Research Lab is no longer a separate portfolio: its five
// strategies were merged into the unified Extreme Lab as the "research" cohort.
// Historical research data is preserved in the DB; the UI now lives at /lab.
export default function ResearchRedirect() {
  redirect("/lab");
}
