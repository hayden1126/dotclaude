"use client";

import dynamic from "next/dynamic";
import Form from "next/form";
import data from "./data.json";
import "./global.css";
import styles from "./styles.module.css";
import { Widget } from "./widget.js";

const Lazy = dynamic(() => import("./lazy"), { loading: () => <p id="loading">loading</p> });

export default function ResolutionPage() {
  return (
    <main>
      <div id="box" className={styles.box}>box</div>
      <p id="json">{data.label}</p>
      <Widget />
      <Lazy word="lazy" />
      <Form id="search" action="/search">
        <input name="q" />
      </Form>
    </main>
  );
}
