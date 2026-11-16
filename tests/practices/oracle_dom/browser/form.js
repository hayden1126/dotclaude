// next/form in the browser bundle: a plain <form>, its action as given (a function stays a
// React form action), without Next's prefetch or client-side navigation.
import { createElement } from "react";

export default function Form({ replace, scroll, prefetch, ...rest }) {
  return createElement("form", rest);
}
