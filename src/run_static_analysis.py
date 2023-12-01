import argparse
import os
import sys
from github import Github
import sa_utils as utils

def extract_info(line, prefix):
    """
    Extracts information from a given line containing file path, line number, and issue description.

    Args:
    - line (str): The input string containing file path, line number, and issue description.
    - prefix (str): The prefix to remove from the start of the file path in the line.
    - was_note (bool): Indicates if the previous issue was a note.
    - output_string (str): The string containing previous output information.

    Returns:
    - tuple: A tuple containing:
        - file_path (str): The path to the file.
        - is_note (bool): A flag indicating if the issue is a note.
        - description (str): Description of the issue.
        - file_line_start (int): The starting line number of the issue.
        - file_line_end (int): The ending line number of the issue.
    """

    # Clean up line
    line = line.replace(prefix, "").lstrip("/")

    # Get the line starting position /path/to/file:line and trim it
    file_path_end_idx = line.index(":")
    file_path = line[:file_path_end_idx]

    # Extract the lines information
    line = line[file_path_end_idx + 1 :]

    # Get line (start, end)
    file_line_start = int(line[: line.index(":")])
    file_line_end = utils.get_file_line_end(file_path, file_line_start)

    # Get content of the issue
    issue_description = line[line.index(" ") + 1 :]
    is_note = issue_description.startswith("note:")

    return (file_path, is_note, file_line_start, file_line_end, issue_description)


def generate_output(is_note, file_path, file_line_start, file_line_end, description):
    """
    Generate a formatted output string based on the details of a code issue.

    This function takes information about a code issue and constructs a string that
    includes details such as the location of the issue in the codebase, the affected code
    lines, and a description of the issue. If the issue is a note, only the description
    is returned. If the issue occurs in a different repository than the target, it
    also fetches the lines where the issue was detected.

    Parameters:
    - is_note (bool): Whether the issue is just a note or a code issue.
    - file_path (str): Path to the file where the issue was detected.
    - file_line_start (int): The line number in the file where the issue starts.
    - file_line_end (int): The line number in the file where the issue ends.
    - description (str): Description of the issue.

    Returns:
    - str: Formatted string with details of the issue.

    Note:
    - This function relies on several global variables like TARGET_REPO_NAME, REPO_NAME,
      FILES_WITH_ISSUES, and SHA which should be set before calling this function.
    """

    if not is_note:
        if utils.TARGET_REPO_NAME != REPO_NAME:
            if file_path not in utils.FILES_WITH_ISSUES:
                try:
                    with open(f"{file_path}") as file:
                        lines = file.readlines()
                        utils.FILES_WITH_ISSUES[file_path] = lines
                except FileNotFoundError:
                    print(f"Error: The file '{file_path}' was not found.")

            modified_content = utils.FILES_WITH_ISSUES[file_path][
                file_line_start - 1 : file_line_end - 1
            ]

            utils.debug_print(
                f"generate_output for following file: \nfile_path={file_path} \nmodified_content={modified_content}\n"
            )

            modified_content[0] = modified_content[0][:-1] + " <---- HERE\n"
            file_content = "".join(modified_content)

            file_url = f"https://github.com/{REPO_NAME}/blob/{SHA}/{file_path}#L{file_line_start}"
            new_line = (
                "\n\n------"
                f"\n\n <b><i>Issue found in file</b></i> [{REPO_NAME}/{file_path}]({file_url})\n"
                f"```cpp\n"
                f"{file_content}"
                f"\n``` \n"
                f"{description} <br>\n"
            )

        else:
            new_line = (
                f"\n\nhttps://github.com/{REPO_NAME}/blob/{SHA}/{file_path}"
                f"#L{file_line_start}-L{file_line_end} {description} <br>\n"
            )
    else:
        new_line = description

    return new_line


def append_issue(is_note, per_issue_string, new_line, list_of_issues):
    if not is_note:
        if len(per_issue_string) > 0 and (per_issue_string not in list_of_issues):
            list_of_issues.append(per_issue_string)
        per_issue_string = new_line
    else:
        per_issue_string += new_line

    return per_issue_string


def create_comment_for_output(
    tool_output, prefix, files_changed_in_pr, output_to_console
):
    """
    Generates a comment for a GitHub pull request based on the tool output.

    Parameters:
        tool_output (str): The tool output to parse.
        prefix (str): The prefix to look for in order to identify issues.
        files_changed_in_pr (dict): A dictionary containing the files that were
            changed in the pull request and the lines that were modified.
        output_to_console (bool): Whether or not to output the results to the console.

    Returns:
        tuple: A tuple containing the generated comment and the number of issues found.
    """

    global CURRENT_COMMENT_LENGTH
    global FILES_WITH_ISSUES
    list_of_issues = []
    per_issue_string = ""
    was_note = False

    for line in tool_output:
        if line.startswith(prefix) and not utils.is_excluded_dir(line):
            (
                file_path,
                is_note,
                file_line_start,
                file_line_end,
                issue_description,
            ) = extract_info(line, prefix)

            # In case where we only output to console, skip the next part
            if output_to_console:
                per_issue_string = append_issue(
                    is_note, per_issue_string, line, list_of_issues
                )
                continue

            if utils.is_part_of_pr_changes(
                file_path, file_line_start, files_changed_in_pr
            ):
                per_issue_string, description = utils.generate_description(
                    is_note,
                    was_note,
                    file_line_start,
                    issue_description,
                    per_issue_string,
                )
                was_note = is_note
                new_line = generate_output(
                    is_note, file_path, file_line_start, file_line_end, description
                )

                if utils.check_for_char_limit(new_line):
                    per_issue_string = append_issue(
                        is_note, per_issue_string, new_line, list_of_issues
                    )
                    utils.CURRENT_COMMENT_LENGTH += len(new_line)

                else:
                    utils.CURRENT_COMMENT_LENGTH = utils.COMMENT_MAX_SIZE

                    return "\n".join(list_of_issues), len(list_of_issues)

    # Append any unprocessed issues
    if len(per_issue_string) > 0 and (per_issue_string not in list_of_issues):
        list_of_issues.append(per_issue_string)

    output_string = "\n".join(list_of_issues)

    utils.debug_print(f"\nFinal output_string = \n{output_string}\n")

    return output_string, len(list_of_issues)


def read_files_and_parse_results():
    """Reads the output files generated by cppcheck and clang-tidy and creates comments
    for the pull request, based on the issues found. The comments can be output to console
    and/or added to the pull request. Returns a tuple with the comments generated for
    cppcheck and clang-tidy, and boolean values indicating whether issues were found by
    each tool, whether output was generated to the console, and whether the actual code
    is in the 'pr_tree' directory.

    Returns:
        A tuple with the following values:
        - cppcheck_comment (str): The comment generated for cppcheck, if any issues were found.
        - clang_tidy_comment (str): The comment generated for clang-tidy, if any issues were found.
        - cppcheck_issues_found (bool): Whether issues were found by cppcheck.
        - clang_tidy_issues_found (bool): Whether issues were found by clang-tidy.
        - output_to_console (bool): Whether output was generated to the console.
    """

    # Get cppcheck and clang-tidy files
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-cc", "--cppcheck", help="Output file name for cppcheck", required=True
    )
    parser.add_argument(
        "-ct", "--clangtidy", help="Output file name for clang-tidy", required=True
    )
    parser.add_argument(
        "-o",
        "--output_to_console",
        help="Whether to output the result to console",
        required=True,
    )
    parser.add_argument(
        "-fk",
        "--fork_repository",
        help="Whether the actual code is in 'pr_tree' directory",
        required=True,
    )
    parser.add_argument(
        "--common",
        default="",
        help="common ancestor between two branches (default: %(default)s)",
    )
    parser.add_argument("--head", default="", help="Head branch (default: %(default)s)")

    if parser.parse_args().fork_repository == "true":
        global REPO_NAME

        # Make sure to use Head repository
        REPO_NAME = os.getenv("INPUT_PR_REPO")

    cppcheck_file_name = parser.parse_args().cppcheck
    clangtidy_file_name = parser.parse_args().clangtidy
    output_to_console = parser.parse_args().output_to_console == "true"

    cppcheck_content = ""
    with open(cppcheck_file_name, "r") as file:
        cppcheck_content = file.readlines()

    clang_tidy_content = ""
    with open(clangtidy_file_name, "r") as file:
        clang_tidy_content = file.readlines()

    common_ancestor = parser.parse_args().common
    feature_branch = parser.parse_args().head

    line_prefix = f"{utils.WORK_DIR}"

    utils.debug_print(
        f"cppcheck result: \n {cppcheck_content} \n"
        f"clang-tidy result: \n {clang_tidy_content} \n"
        f"line_prefix: {line_prefix} \n"
    )

    files_changed_in_pr = dict()
    if not output_to_console and (utils.ONLY_PR_CHANGES == "true"):
        files_changed_in_pr = utils.get_changed_files(common_ancestor, feature_branch)

    cppcheck_comment, cppcheck_issues_found = create_comment_for_output(
        cppcheck_content, line_prefix, files_changed_in_pr, output_to_console
    )
    clang_tidy_comment, clang_tidy_issues_found = create_comment_for_output(
        clang_tidy_content, line_prefix, files_changed_in_pr, output_to_console
    )

    if output_to_console and (cppcheck_issues_found or clang_tidy_issues_found):
        print("##[error] Issues found!\n")
        error_color = "\u001b[31m"

        if cppcheck_issues_found:
            print(f"{error_color}cppcheck results: {cppcheck_comment}")

        if clang_tidy_issues_found:
            print(f"{error_color}clang-tidy results: {clang_tidy_comment}")

    return (
        cppcheck_comment,
        clang_tidy_comment,
        cppcheck_issues_found,
        clang_tidy_issues_found,
        output_to_console,
    )


def prepare_comment_body(
    cppcheck_comment, clang_tidy_comment, cppcheck_issues_found, clang_tidy_issues_found
):
    """
    Generates a comment body based on the results of the cppcheck and clang-tidy analysis.

    Args:
        cppcheck_comment (str): The comment body generated for the cppcheck analysis.
        clang_tidy_comment (str): The comment body generated for the clang-tidy analysis.
        cppcheck_issues_found (int): The number of issues found by cppcheck analysis.
        clang_tidy_issues_found (int): The number of issues found by clang-tidy analysis.

    Returns:
        str: The final comment body that will be posted as a comment on the pull request.
    """

    if cppcheck_issues_found == 0 and clang_tidy_issues_found == 0:
        full_comment_body = (
            '## <p align="center"><b> :white_check_mark:'
            f"{utils.COMMENT_TITLE} - no issues found! :white_check_mark: </b></p>"
        )
    else:
        full_comment_body = (
            f'## <p align="center"><b> :zap: {utils.COMMENT_TITLE} :zap: </b></p> \n\n'
        )

        if len(cppcheck_comment) > 0:
            full_comment_body += (
                f"<details> <summary> <b> :red_circle: cppcheck found "
                f"{cppcheck_issues_found} {'issues' if cppcheck_issues_found > 1 else 'issue'}!"
                " Click here to see details. </b> </summary> <br>"
                f"{cppcheck_comment} </details>"
            )

        full_comment_body += "\n\n *** \n"

        if len(clang_tidy_comment) > 0:
            full_comment_body += (
                f"<details> <summary> <b> :red_circle: clang-tidy found "
                f"{clang_tidy_issues_found} {'issues' if clang_tidy_issues_found > 1 else 'issue'}!"
                " Click here to see details. </b> </summary> <br>"
                f"{clang_tidy_comment} </details><br>\n"
            )

    if utils.CURRENT_COMMENT_LENGTH == utils.COMMENT_MAX_SIZE:
        full_comment_body += f"\n```diff\n{utils.MAX_CHAR_COUNT_REACHED}\n```"

    utils.debug_print(f"Repo={REPO_NAME} pr_num={utils.PR_NUM} comment_title={utils.COMMENT_TITLE}")

    return full_comment_body


def create_or_edit_comment(comment_body):
    """
    Creates or edits a comment on a pull request with the given comment body.

    Args:
    - comment_body: A string containing the full comment body to be created or edited.

    Returns:
    - None.
    """

    github = Github(utils.GITHUB_TOKEN)
    repo = github.get_repo(utils.TARGET_REPO_NAME)
    pull_request = repo.get_pull(int(utils.PR_NUM))

    comments = pull_request.get_issue_comments()
    found_id = -1
    comment_to_edit = None
    for comment in comments:
        if (comment.user.login == "github-actions[bot]") and (
            utils.COMMENT_TITLE in comment.body
        ):
            found_id = comment.id
            comment_to_edit = comment
            break

    if found_id != -1 and comment_to_edit:
        comment_to_edit.edit(body=comment_body)
    else:
        pull_request.create_issue_comment(body=comment_body)


if __name__ == "__main__":
    (
        cppcheck_comment_in,
        clang_tidy_comment_in,
        cppcheck_issues_found_in,
        clang_tidy_issues_found_in,
        output_to_console_in,
    ) = read_files_and_parse_results()

    if not output_to_console_in:
        comment_body_in = prepare_comment_body(
            cppcheck_comment_in,
            clang_tidy_comment_in,
            cppcheck_issues_found_in,
            clang_tidy_issues_found_in,
        )
        create_or_edit_comment(comment_body_in)

    sys.exit(cppcheck_issues_found_in + clang_tidy_issues_found_in)
