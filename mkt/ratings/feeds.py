from reviews.feeds import ReviewsRss


class RatingsRss(ReviewsRss):

    def item_link(self, review):
        """Link for a particular review(<item><link)"""
        return self.addon.get_ratings_url('detail', args=[review.id])

    def item_guid(self, review):
        """Guid for a particular review(<item><link)"""
        return self.addon.get_ratings_url('list')
