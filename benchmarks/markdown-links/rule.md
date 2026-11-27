Notes in this folder link to each other with relative Markdown links, never [[wikilinks]] in the body: write each path relative to the note that holds it, with spaces and special characters percent-encoded, for example [Jane](../People/Jane%20Doe.md). Frontmatter lists notes as quoted wikilinks, like "[[Jane Doe]]".
When you move or rename a note or folder, use git mv, then update every link to and from it, including frontmatter wikilinks.
When you delete a note, don't remove or repoint the links to it; list them and ask the user what to do.
