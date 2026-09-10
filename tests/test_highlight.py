from runhealth.highlight import bash_html


def test_sbatch_directives_are_marked_apart_from_comments():
    html = bash_html("#SBATCH --nodes=2\n# just a note\n")
    assert '<span class="sy-dir">#SBATCH --nodes=2</span>' in html
    assert '<span class="sy-cmt"># just a note</span>' in html


def test_keywords_commands_strings_and_variables():
    html = bash_html('if true; then echo "n=$SLURM_NNODES"; fi')
    assert '<span class="sy-kw">if</span>' in html
    assert '<span class="sy-kw">then</span>' in html
    assert '<span class="sy-cmd">echo</span>' in html
    assert '<span class="sy-str">' in html
    # A quoted string still expands what is inside it.
    assert '<span class="sy-var">$SLURM_NNODES</span>' in html


def test_a_hash_inside_a_word_is_not_a_comment():
    html = bash_html("echo ${name#prefix}")
    assert "sy-cmt" not in html
    assert '<span class="sy-var">${name#prefix}</span>' in html


def test_a_trailing_comment_is_still_a_comment():
    assert '<span class="sy-cmt"># why</span>' in bash_html("srun ./model  # why")


def test_everything_is_escaped():
    html = bash_html("echo '<script>alert(1)</script>' # <b>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>" not in html


def test_plain_text_survives_unchanged():
    assert bash_html("") == ""
    assert bash_html("plain_words 42\n") == "plain_words 42\n"
