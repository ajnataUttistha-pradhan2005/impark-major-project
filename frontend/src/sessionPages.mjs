/** @typedef {import('./types').Session} Session */

/**
 * Load the full sidebar before treating an empty list as "no chats".
 * A request generation check prevents an older refresh from restoring a
 * session after it was deleted or after the archived view changed.
 * @param {(archived: boolean, offset: number) => Promise<{items: Session[], next_offset: number | null}>} getPage
 * @param {boolean} archived
 * @param {() => boolean} isCurrent
 * @returns {Promise<Session[] | null>}
 */
export async function loadAllSessions(getPage, archived, isCurrent) {
  /** @type {Session[]} */
  const items = [];
  let offset = 0;
  while (isCurrent()) {
    const page = await getPage(archived, offset);
    if (!isCurrent()) return null;
    items.push(...page.items);
    if (page.next_offset === null) return items;
    if (page.next_offset <= offset || page.next_offset > 100000) {
      throw new Error('Invalid session page cursor');
    }
    offset = page.next_offset;
  }
  return null;
}
