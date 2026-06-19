export default function Setup() {
  return (
    <div className="empty">
      <h2>Almost there — connect Supabase</h2>
      <p className="muted">
        This dashboard reads the bot's public data straight from Supabase. Set
        two environment variables (locally in <code>web/.env</code>, or in your
        Vercel project settings) and redeploy:
      </p>
      <pre>
        <code>{`VITE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-public-key`}</code>
      </pre>
      <p className="muted">
        Both values are public by design — Row Level Security on the database
        makes the anon key read-only. Find them in Supabase under{" "}
        <strong>Project Settings → API</strong>.
      </p>
    </div>
  );
}
