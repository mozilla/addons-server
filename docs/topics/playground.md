# Playground

(syntax)=
## Syntax

### Admonitions

```{admonition} This is a title
  An example of an admonition with a _title_.
```

### List

1. quotes
2. breaks
3. links

### Code

```python
print('this is python')
```

```javascript
console.log('this is python')
```

### Blockquotes

> To be or not to be

### Breaks

thematic

---

break

### HTML

<div><p>*some text*</p></div>

### Links

This is an inline link to a [search engine](https://www.google.com "Google")

Here is a referenced link to [Google][google].

You can link to files like [README](../README.md).

You can link to a particular section like [Syntax](#syntax).

[google]: https://www.google.com "Google"

Link to a named reference anchor

see {ref}`my-table`

```{list-table}  Caption text
:name: my-table

*   - Head 1
*   - Row 1
```

You can link to a named anchor

{ref}`Link <header_link>`

(header_link)=
#### Head to Link to

Here is the content

### Images

You can inline render images

![favicon](../../static/img/favicon.ico)

### Formatting

**strong**, _emphasis_, `literal text`, \*escaped symbols\*

### Tables

| header 1 | header 2 |
|:---|---:|
| 3 | 4 |


### Footnotes

Here's a simple footnote,[^1] and here's a longer one.[^bignote]

[^1]: This is the first footnote.

[^bignote]: Here's one with multiple paragraphs and code.

    Indent paragraphs to include them in the footnote.

    `{ my code }`

    Add as many paragraphs as you like.
