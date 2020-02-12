from praw import Reddit
from praw.models import Submission
from praw.reddit import Subreddit
from dotenv import load_dotenv
import os
import numpy as np
import pickledb
from typing import Union, Tuple

# I've saved my API token information to a .env file, which gets loaded here
load_dotenv()
client = os.getenv("CLIENT_ID")
secret = os.getenv("CLIENT_SECRET")
username = os.getenv("USERNAME")
password = os.getenv("PASSWORD")

# Set the path absolute path of the chess_post database
pickle_path = os.path.dirname(os.path.abspath(__file__)) + '/chess_posts.db'
db = pickledb.load(pickle_path, True)

# Create the reddit object instance using Praw
reddit = Reddit(user_agent='RelevantChessPostBot',
                client_id=client, client_secret=secret,
                username=username, password=password)
# Constants
CERTAINTY_THRESHOLD = .50
SIMILARITY_THRESHOLD = .40


def run():
    # Instantiate the subreddit instances
    chess: Subreddit = reddit.subreddit('chess')
    anarchychess: Subreddit = reddit.subreddit('anarchychess')

    # This loops forever, streaming submissions in real time from r/anarchychess as they get posted
    for ac_post in anarchychess.stream.submissions():
        print("Analyzing post: ", ac_post.title)

        # Gets the r/chess post in hot with the minimum levenshtein distance
        relevant_post, min_distance = get_min_levenshtein(ac_post, chess)

        # Are the post's words similar and to what degree?
        sim_bool, similarity = is_similar(ac_post, relevant_post, SIMILARITY_THRESHOLD)

        if relevant_post and sim_bool:
            max_length = float(max(len(ac_post.title.split()), len(relevant_post.title.split())))

            # Certainty is calculated with this arbitrary formula that seems to work well
            certainty = similarity * (1 - (min_distance / max_length))

            # Log useful stats
            print("Minimum distance:", min_distance)
            print("Maximum length:", max_length)
            print("Similarity:", similarity)
            print("AC title: ", ac_post.title)
            print("C title: ", relevant_post.title)
            print("Certainty: ", certainty)

            if certainty > CERTAINTY_THRESHOLD:
                try:
                    if ac_post.comments and username in [comment.author.name for comment in ac_post.comments]:
                        print("Already commented")
                    else:
                        add_comment(ac_post, relevant_post, certainty)

                except Exception as e:
                    print("Was rate limited", e)
                    pass

                # update the original r/chess post's comment with the relevant AC posts
                try:
                    add_chess_comment(relevant_post, ac_post)

                except Exception as e:
                    print("Was rate limited", e)
                    pass


def add_comment(ac_post: Submission, relevant_post: Submission, certainty) -> None:
    """
    Adds a comment to the AnarchyChess post. If anyone knows how to format it so my username is also superscripted,
    please submit a PR.

    :param ac_post: AnarchyChess post
    :param relevant_post: Chess post
    :param certainty: Certainty metric
    :return: None
    """
    reply_template = "Relevant r/chess post: [{}](https://www.reddit.com{})\n\n".format(relevant_post.title,
                                                                                        relevant_post.permalink)
    certainty_tag = "Certainty: {}%\n\n".format(round(certainty * 100, 2))
    bot_tag = "^I ^am ^a ^bot ^created ^by ^(^(/u/fmhall)), ^inspired ^by [^(this comment.)]({})\n\n".format(
        "https://www.reddit.com/r/AnarchyChess/comments/durvcj/dude_doesnt_play_chess_thinks_he_can_beat_magnus/f78cga9")
    github_tag = ("^(I use the Levenshtein distance of both titles to determine relevance."
                  "\nYou can find my source code [here]({}))".format("https://github.com/fmhall/relevant-post-bot"))
    comment = reply_template + certainty_tag + bot_tag + github_tag
    ac_post.reply(comment)
    print(comment)


def add_chess_comment(relevant_post: Submission, ac_post: Submission) -> None:
    rpid = str(relevant_post.id)
    acpid = str(ac_post.id)
    if not db.get(rpid):
        db.set(rpid, [acpid])
    else:
        rid_list = db.get(rpid)
        rid_list = list(set(rid_list))
        if acpid not in rid_list:
            rid_list.append(acpid)
        db.set(rpid, rid_list)
    posts = [reddit.submission(id=p) for p in db.get(rpid)]
    posts.sort(key=lambda x: x.score, reverse=True)
    posts_string = "".join(
        ["[{} upvotes][{}](https://www.reddit.com{}) by {}\n\n".format(p.score, p.title, p.permalink, p.author) for p in
         posts])
    reply_template = "This post has been parodied on r/anarchychess.\n\n" \
                     "Relevant r/anarchychess posts: \n\n{}".format(posts_string)

    bot_tag = "^I ^am ^a ^bot ^created ^by ^/u/fmhall, ^inspired ^by [^(this comment.)]({})\n\n".format(
        "https://www.reddit.com/r/AnarchyChess/comments/durvcj/dude_doesnt_play_chess_thinks_he_can_beat_magnus/f78cga9")
    github_tag = ("^(I use the Levenshtein distance of both titles to determine relevance."
                  "\nYou can find my source code [here]({}))".format("https://github.com/fmhall/relevant-post-bot"))
    comment_string = reply_template + bot_tag + github_tag
    if relevant_post.comments and username not in [comment.author.name for comment in relevant_post.comments]:
        relevant_post.reply(comment_string)
    else:
        for comment in relevant_post.comments:
            if comment.author.name == username:
                comment.edit(comment_string)
                print("edited")
    print(comment_string)


def get_min_levenshtein(ac_post: Submission, chess: Subreddit) -> (Submission, float):
    """
    This function iterates through the hot posts in the Chess subreddit and finds the one with the smallest levenshtein
    distance to the AnarchyChess post.
    :param ac_post: AnarchyChess post
    :param chess: Chess subreddit
    :return: tuple with the r/chess post with the smallest LD, and the distance
    """
    ac_title: str = ac_post.title
    min_distance = 100000
    relevant_post = None
    for c_post in chess.hot():
        c_title = c_post.title
        distance = levenshtein(ac_title.split(), c_title.split())
        if distance < min_distance:
            min_distance = distance
            relevant_post = c_post
    return relevant_post, min_distance


def is_similar(ac_post: Submission, c_post: Submission, factor: float) -> Tuple[bool, float]:
    """

    :param ac_post: AnarchyChess post
    :param c_post: Chess post
    :param factor: float indicating smallest proportion of similar words
    :return: boolean indicating if the proportion is similar and the proportion of words the posts
    share divided by the length of the longer post
    """
    ac_title_set = set(ac_post.title.split())
    c_title_set = set(c_post.title.split())
    similarity = len(ac_title_set.intersection(c_title_set))
    sim_ratio = similarity / max(len(ac_title_set), len(c_title_set))

    if sim_ratio > factor:
        return True, sim_ratio

    return False, 0.0


def levenshtein(seq1: list, seq2: list) -> float:
    """
    The Levenshtein distance is a string metric for measuring the difference between two sequences. Informally,
    the Levenshtein distance between two words is the minimum number of single-character edits (i.e. insertions,
    deletions, or substitutions) required to change one word into the other. While it is normally used to compare
    characters in a sequence, if you treat each word in a sentence like a character, then it can be used on sentences.
    :param seq1: First sentence
    :param seq2: Second sentence
    :return: The levenshtein distance between the two
    """
    size_x = len(seq1) + 1
    size_y = len(seq2) + 1
    matrix = np.zeros((size_x, size_y))
    for x in range(size_x):
        matrix[x, 0] = x
    for y in range(size_y):
        matrix[0, y] = y
    for x in range(1, size_x):
        for y in range(1, size_y):
            if seq1[x - 1] == seq2[y - 1]:
                matrix[x, y] = min(matrix[x - 1, y] + 1, matrix[x - 1, y - 1], matrix[x, y - 1] + 1)
            else:
                matrix[x, y] = min(
                    matrix[x - 1, y] + 1,
                    matrix[x - 1, y - 1] + 1,
                    matrix[x, y - 1] + 1
                )
    return float(matrix[size_x - 1, size_y - 1])


if __name__ == "__main__":
    run()
