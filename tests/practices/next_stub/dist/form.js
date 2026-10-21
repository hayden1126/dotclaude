// next/form's <Form> renders the <form> it stands for: a function action submits like any
// form's, and a string action is a GET to that URL (Next navigates to it with the fields as
// the query). prefetch, replace and scroll only steer client-side navigation.
const element = (type, props) => ({ $$typeof: Symbol.for("react.element"), type, props });

export default function Form({ replace, scroll, prefetch, ...props }) {
  return element("form", typeof props.action === "string" ? { ...props, method: "get" } : props);
}
