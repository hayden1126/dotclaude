import { useFormStatus } from "react-dom";

// Planted: a client-only react-dom hook with no "use client" above it, which Next refuses.
export default function NoDirectiveForm() {
  const { pending } = useFormStatus();
  return <p>{String(pending)}</p>;
}
