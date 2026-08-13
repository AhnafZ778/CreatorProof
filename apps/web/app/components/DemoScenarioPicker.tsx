"use client";

/**
 * One-click demo scenarios.
 *
 * The portal is unusable as a demonstration from a cold start: a reviewer has
 * nothing to upload and no catalog to scan against, so the first screen they
 * see is an empty form. Each card here builds its own reference works and
 * candidate in the browser, registers them into a catalog created for that run,
 * and starts the scan — no fixtures, no network, and no shared state between
 * runs to make counts drift.
 *
 * Every card states the lane it exercises and the honest expected outcome,
 * including the ones that should land in review rather than a clean pass.
 */

import { DEMO_SCENARIOS, type DemoScenario } from "@/app/lib/demoScenarios";

export default function DemoScenarioPicker({
  onRun,
  runningId,
  disabled,
}: {
  onRun: (scenario: DemoScenario) => void;
  runningId: string | null;
  disabled?: boolean;
}) {
  return (
    <section className="demoPicker" aria-label="Demo scenarios">
      <header className="demoPickerHeading">
        <small>Try it without an image</small>
        <h3>Run a prepared scenario</h3>
        <p>
          Each scenario generates its own reference works and candidate in this browser, registers
          them into a fresh catalog, and runs a real scan against the live engine.
        </p>
      </header>

      <div className="demoScenarioGrid">
        {DEMO_SCENARIOS.map((scenario) => {
          const running = runningId === scenario.id;
          return (
            <button
              key={scenario.id}
              type="button"
              className={`demoScenarioCard${running ? " isRunning" : ""}`}
              data-lane={scenario.laneKey}
              onClick={() => onRun(scenario)}
              disabled={disabled}
              aria-busy={running}
            >
              <span className="demoScenarioLane">{scenario.lane}</span>
              <b>{scenario.title}</b>
              <span className="demoScenarioQuestion">{scenario.question}</span>
              <span className="demoScenarioExpectation">{scenario.expectation}</span>
              <em className="demoScenarioCaveat">{scenario.caveat}</em>
              <span className="demoScenarioAction">
                {running ? "Preparing scenario…" : "Run this scenario →"}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
