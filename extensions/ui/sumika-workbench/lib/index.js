// Host half: native human-command admission for explicitly confirmed schedules.
// DSH retains all timing, task catalog and delivery ownership.

export const name = 'sumika-workbench';

import {applySchedule} from '../../../desktop/schedule_dsh.mjs';
export const inject=['commands','schedule','workspaceRegistry'];
export function apply(ctx,config) {applySchedule(ctx,config);}
