/* One sentence for one event.
 *
 * Three surfaces reported the same condition in three wordings — the tracker's
 * outlook said "Requires the local AI. Install Ollama to enable", the chat said
 * "Local AI is offline. Install and start Ollama", the debate said a third
 * thing — so the app had three voices for a single fact about the machine it is
 * running on. They are never on screen together, which is exactly why the drift
 * went unnoticed.
 *
 * What differs between them is real and is kept: `children` carries the clause
 * that is true only of that surface. Nothing was dropped in the merge.
 */
export default function AiOffline({ children }) {
  return (
    <div className="ai-offline-note">
      Local AI is offline. Install and start Ollama to enable this (see README).
      {children ? ' ' : ''}
      {children}
    </div>
  );
}
