import OriginalAdmin from "./AdminDashboard";
import DatabaseSchema from "./DatabaseSchemaER";

// Admin-only page component is wrapped, not rewritten.
// Its original content and state are preserved; schema appears at the bottom.
export default function AdminSchemaWrapped(props) {
  return <>
    <OriginalAdmin {...props} />
    <DatabaseSchema />
  </>;
}
