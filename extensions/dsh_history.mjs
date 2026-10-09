// Harness-specific compatibility boundary. Core services never import this file.
export async function sessionEvents(ctx, session, fromSeq = 0) {
  if (ctx.sessionQuery?.readSession) {
    const snapshot = await ctx.sessionQuery.readSession(session.header.id);
    if (!Array.isArray(snapshot.events)) throw Error('invalid DSH history snapshot');
    return snapshot.events.filter(event => event.seq >= fromSeq);
  }
  return session.snapshotEvents(fromSeq);
}
