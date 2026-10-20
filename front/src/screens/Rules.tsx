import { api } from "../api";
import { ErrorBox, Loading, useAsync } from "../components/common";

/** "Como o Encaixe decide": the HTML is rendered on the server from app/config.py (no number typed here). */
export function Rules() {
  const { data, error, loading } = useAsync(() => api.get<{ html: string; hash: string }>("/api/rules"), []);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <article className="rules-page" aria-label="Como o Encaixe decide"
      dangerouslySetInnerHTML={{ __html: data?.html ?? "" }} />
  );
}
