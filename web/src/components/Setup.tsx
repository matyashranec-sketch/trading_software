import Card from "./ui/Card";

export default function Setup() {
  return (
    <Card className="panel setup">
      <h2 style={{ marginTop: 0 }}>Almost there — connect Supabase</h2>
      <p className="empty-note">
        This dashboard reads the bot's public data straight from Supabase. Set two
        environment variables (locally in <code>web/.env</code>, or in your Vercel
        project settings) and redeploy:
      </p>
      <pre>
        <code>{`VITE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-public-key`}</code>
      </pre>
      <p className="empty-note">
        Both values are public by design — Row Level Security on the database makes
        the anon key read-only. Find them in Supabase under{" "}
        <strong>Project Settings → API</strong>.
      </p>
    </Card>
  );
}
