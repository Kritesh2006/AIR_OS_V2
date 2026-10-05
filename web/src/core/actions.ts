/**
 * actions.ts — Web version of the desktop ActionProvider contract
 * (desktop contracts.py). Providers act only on things this page owns.
 */

export interface Target {
  readonly id: string;
  readonly label: string;
  readonly sublabel: string;
  readonly icon: string;
}

export type ActionStatus = 'SENT' | 'CLOSED' | 'STILL_OPEN' | 'FAILED' | 'GONE_BEFORE';

export interface ActionResult {
  readonly status: ActionStatus;
  readonly detail: string;
}

export interface ActionProvider {
  readonly id: string;
  readonly risk: 'low' | 'high';
  /** Snapshot of what can be acted on right now. */
  listTargets(): Target[];
  /** Perform the action on one target. Must re-check the target exists. */
  execute(target: Target): ActionResult;
}
