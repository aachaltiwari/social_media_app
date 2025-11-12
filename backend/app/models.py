import uuid
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings 
from django.contrib.auth.models import AbstractUser


# ============================================================
# 0. CUSTOM USER MODEL (UUID-based)
# ============================================================
class CustomUser(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # You can add extra fields if needed later (bio, phone, etc.)

    def __str__(self):
        return self.username



# ============================================================
# 1. PROFILE
# ============================================================
class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    profile_picture = models.ImageField(upload_to="profiles/", blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Symmetrical friendship (mutual connection)
    friends = models.ManyToManyField("self", symmetrical=True, blank=True, related_name="friends_with")

    def __str__(self):
        return f"{self.user.username}'s Profile"

    def visible_posts(self, viewer, page_number: int = 1, page_size: int = 10):
        """Return paginated posts visible to the viewer (only friends or owner)."""
        if not viewer.is_authenticated:
            return self.user.posts.none()

        if viewer == self.user or self.friends.filter(pk=viewer.profile.pk).exists():
            return self.user.posts.all().order_by('-created_at')[
                (page_number - 1) * page_size : page_number * page_size
            ]
        return self.user.posts.none()

    def is_friend_with(self, other_user):
        """Check if current profile is friends with another user."""
        return self.friends.filter(pk=other_user.profile.pk).exists()

    def send_friend_request(self, to_user):
        """Helper to safely send a friend request."""
        if to_user == self.user:
            raise ValueError("You cannot send a friend request to yourself.")
        if FriendRequest.objects.filter(sender=self.user, receiver=to_user, status="pending").exists():
            raise ValueError("Friend request already sent.")
        return FriendRequest.objects.create(sender=self.user, receiver=to_user)

    def get_friends(self, page_number: int = 1, page_size: int = 10):
        """Return paginated list of this user's friends."""
        start = (page_number - 1) * page_size
        end = page_number * page_size
        return self.friends.all()[start:end]

    def friend_count(self):
        """Return total number of friends of the user."""
        return self.friends.count()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


# ============================================================
# 2. FRIEND REQUEST
# ============================================================
class FriendRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
    ]

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="sent_requests", on_delete=models.CASCADE)
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="received_requests", on_delete=models.CASCADE)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("sender", "receiver")
        indexes = [models.Index(fields=["receiver", "status"])]

    def __str__(self):
        return f"{self.sender.username} → {self.receiver.username} ({self.status})"

    def accept(self):
        if self.status != "pending":
            return
        self.status = "accepted"
        self.save()
        sender_profile = self.sender.profile
        receiver_profile = self.receiver.profile
        sender_profile.friends.add(receiver_profile)
        receiver_profile.friends.add(sender_profile)

    def reject(self):
        if self.status == "pending":
            self.status = "rejected"
            self.delete()

    def cancel(self):
        if self.status == "pending":
            self.delete()


# ============================================================
# 3. POST
# ============================================================
class Post(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts")
    content = models.TextField()
    image = models.ImageField(upload_to="posts/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self):
        return f"Post #{self.pk} by {self.author.username}"

    def has_reacted(self, user):
        if not user.is_authenticated:
            return False
        return self.reactions.filter(user=user).exists()

    @property
    def total_reactions(self):
        return self.reactions.count()

    @property
    def total_comments(self):
        return self.comments.count()


# ============================================================
# 4. REACTION
# ============================================================
class Reaction(models.Model):
    REACTION_CHOICES = [
        ("like", "Like"),
        ("love", "Love"),
        ("haha", "Haha"),
        ("angry", "Angry"),
        ("sad", "Sad"),
    ]

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_reactions")
    reaction_type = models.CharField(max_length=10, choices=REACTION_CHOICES, default="like")
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("post", "user")
        indexes = [models.Index(fields=["post", "user", "reaction_type"])]

    def __str__(self):
        return f"{self.user.username} reacted '{self.get_reaction_type_display()}' on Post #{self.post.pk}"


# ============================================================
# 5. COMMENT
# ============================================================
class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_comments")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user.username} commented on Post #{self.post.pk}"

    def can_user_comment(self, user):
        post_author = self.post.author
        if user == post_author:
            return True
        return user.profile.is_friend_with(post_author)
