export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.NEXT_PHASE === "phase-production-build") return;
  try {
    const { validateServerEnvironment } = await import("./app/lib/serverEnv");
    validateServerEnvironment();
  } catch (caught) {
    // Missing Render/API secrets must not take down the marketing homepage.
    // Protected routes and API handlers still fail closed when they read config.
    console.error(caught);
  }
}
